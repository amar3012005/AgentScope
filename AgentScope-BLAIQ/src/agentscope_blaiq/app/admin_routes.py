from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentscope_blaiq.persistence.database import get_db
from agentscope_blaiq.persistence.models import (
    UserRecord, WorkspaceRecord, RoleRecord, PermissionRecord, 
    workspace_members, AuditLogRecord, PolicySetRecord, PolicyRuleRecord
)
from agentscope_blaiq.runtime.config import settings

router = APIRouter(prefix="/api/v1/admin")

async def get_current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> UserRecord:
    from agentscope_blaiq.persistence.models import SessionRecord, ApiKeyRecord
    user_id: str | None = None
    
    # 1. Session cookie
    session_token = request.cookies.get("hm_session")
    if session_token:
        result = await db.execute(
            select(SessionRecord).where(
                SessionRecord.token == session_token,
                SessionRecord.expires_at > datetime.now(timezone.utc)
            )
        )
        if s := result.scalar_one_or_none():
            user_id = s.user_id

    # 2. Bearer token
    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            import hashlib
            token = auth_header[7:]
            key_hash = hashlib.sha256(token.encode()).hexdigest()
            result = await db.execute(
                select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
            )
            if k := result.scalar_one_or_none():
                user_id = k.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await db.get(UserRecord, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.is_superuser:
        # Check if user has admin role in ANY workspace for now, 
        # or just strictly superuser for global admin. 
        # The prompt says "Check workspace_members for admin role"
        stmt = select(workspace_members).join(RoleRecord, workspace_members.c.role_id == RoleRecord.id).where(
            workspace_members.c.user_id == user.id,
            RoleRecord.name == "admin"
        )
        res = await db.execute(stmt)
        if not res.first():
            raise HTTPException(status_code=403, detail="Admin access required")
            
    return user

async def log_audit(db: AsyncSession, user_id: str, action: str, resource_type: str, resource_id: Optional[str] = None, workspace_id: Optional[str] = None, details: dict = {}):
    audit = AuditLogRecord(
        workspace_id=workspace_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details_json=json.dumps(details)
    )
    db.add(audit)
    # We assume the caller will commit or we commit inside mutation routes

# --- Member Management ---

class MemberInviteRequest(BaseModel):
    email: EmailStr
    role_name: str
    workspace_id: str

@router.get("/members")
async def list_members(workspace_id: str, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    # List all users in the specific workspace
    stmt = select(UserRecord, RoleRecord.name).join(
        workspace_members, UserRecord.id == workspace_members.c.user_id
    ).join(
        RoleRecord, workspace_members.c.role_id == RoleRecord.id
    ).where(workspace_members.c.workspace_id == workspace_id)
    
    result = await db.execute(stmt)
    members = []
    for user, role_name in result:
        members.append({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": role_name,
            "is_active": user.is_active
        })
    return {"members": members}

@router.post("/members/invite")
async def invite_member(req: MemberInviteRequest, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    # 1. Find or create user
    stmt = select(UserRecord).where(UserRecord.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if not user:
        user = UserRecord(email=req.email, is_active=True)
        db.add(user)
        await db.flush()
    
    # 2. Find role
    stmt = select(RoleRecord).where(RoleRecord.name == req.role_name)
    res = await db.execute(stmt)
    role = res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {req.role_name} not found")
    
    # 3. Add to workspace
    # Check if already a member
    stmt = select(workspace_members).where(
        workspace_members.c.workspace_id == req.workspace_id,
        workspace_members.c.user_id == user.id
    )
    if (await db.execute(stmt)).first():
        raise HTTPException(status_code=400, detail="User already in workspace")
        
    await db.execute(workspace_members.insert().values(
        workspace_id=req.workspace_id,
        user_id=user.id,
        role_id=role.id
    ))
    
    await log_audit(db, admin.id, "member.invited", "user", user.id, req.workspace_id, {"role": req.role_name})
    await db.commit()
    return {"ok": True, "user_id": user.id}

class RoleUpdateRequest(BaseModel):
    role_name: str
    workspace_id: str

@router.patch("/members/{user_id}/role")
async def update_member_role(user_id: str, req: RoleUpdateRequest, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    stmt = select(RoleRecord).where(RoleRecord.name == req.role_name)
    res = await db.execute(stmt)
    role = res.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
        
    stmt = update(workspace_members).where(
        workspace_members.c.workspace_id == req.workspace_id,
        workspace_members.c.user_id == user_id
    ).values(role_id=role.id)
    
    res = await db.execute(stmt)
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
        
    await log_audit(db, admin.id, "member.role_changed", "user", user_id, req.workspace_id, {"new_role": req.role_name})
    await db.commit()
    return {"ok": True}

@router.delete("/members/{user_id}")
async def remove_member(user_id: str, workspace_id: str, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    stmt = delete(workspace_members).where(
        workspace_members.c.workspace_id == workspace_id,
        workspace_members.c.user_id == user_id
    )
    res = await db.execute(stmt)
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
        
    await log_audit(db, admin.id, "member.removed", "user", user_id, workspace_id)
    await db.commit()
    return {"ok": True}

# --- Policy Management ---

class PolicyRuleSchema(BaseModel):
    rule_type: str
    effect: str = "allow"
    resource_pattern: str

class PolicySetCreate(BaseModel):
    name: str
    workspace_id: str
    rules: List[PolicyRuleSchema]

@router.get("/policies")
async def list_policies(workspace_id: str, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    stmt = select(PolicySetRecord).where(
        PolicySetRecord.workspace_id == workspace_id,
        PolicySetRecord.is_active == True
    ).options(selectinload(PolicySetRecord.rules))
    
    res = await db.execute(stmt)
    return {"policies": res.scalars().all()}

@router.post("/policies")
async def create_policy(req: PolicySetCreate, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    ps = PolicySetRecord(name=req.name, workspace_id=req.workspace_id, is_active=True)
    db.add(ps)
    await db.flush()
    
    for r in req.rules:
        rule = PolicyRuleRecord(
            policy_set_id=ps.id,
            rule_type=r.rule_type,
            effect=r.effect,
            resource_pattern=r.resource_pattern
        )
        db.add(rule)
        
    await log_audit(db, admin.id, "policy.created", "policy_set", ps.id, req.workspace_id, {"name": req.name})
    await db.commit()
    return {"ok": True, "id": ps.id}

@router.delete("/policies/{policy_id}")
async def delete_policy(policy_id: str, db: AsyncSession = Depends(get_db), admin: UserRecord = Depends(get_current_admin)):
    ps = await db.get(PolicySetRecord, policy_id)
    if not ps:
        raise HTTPException(status_code=404, detail="Policy not found")
        
    ps.is_active = False
    await log_audit(db, admin.id, "policy.deleted", "policy_set", policy_id, ps.workspace_id)
    await db.commit()
    return {"ok": True}

# --- Audit Log ---

@router.get("/audit")
async def get_audit_logs(
    workspace_id: Optional[str] = None,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: UserRecord = Depends(get_current_admin)
):
    stmt = select(AuditLogRecord)
    if workspace_id:
        stmt = stmt.where(AuditLogRecord.workspace_id == workspace_id)
    if action:
        stmt = stmt.where(AuditLogRecord.action == action)
    if user_id:
        stmt = stmt.where(AuditLogRecord.user_id == user_id)
    if from_date:
        stmt = stmt.where(AuditLogRecord.created_at >= from_date)
    if to_date:
        stmt = stmt.where(AuditLogRecord.created_at <= to_date)
        
    stmt = stmt.order_by(AuditLogRecord.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    logs = res.scalars().all()
    
    return {
        "logs": logs,
        "limit": limit,
        "offset": offset
    }
