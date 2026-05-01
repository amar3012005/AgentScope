import asyncio
import json
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from agentscope_blaiq.persistence.models import Base, ConversationRecord, ConversationMessageRecord, WorkflowRecord
from agentscope_blaiq.persistence.repositories import ConversationRepository
from agentscope_blaiq.contracts.workflow import SubmitWorkflowRequest, WorkflowMode, AnalysisMode
from agentscope_blaiq.workflows.swarm_workflow_engine import SwarmWorkflowEngine

# Mock Registry for testing
class MockRegistry:
    def __init__(self):
        self.user_agent_registry = None

async def test_persistence():
    print("Testing Chat Persistence Flow...")
    
    # Use in-memory SQLite for testing
    TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(TEST_DB_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_session() as session:
        conv_repo = ConversationRepository(session)
        
        # 1. Test Repository Directly
        print("\n1. Testing Repository...")
        thread_id = str(uuid.uuid4())
        workspace_id = "test-ws"
        user_id = "test-user"
        
        conv = await conv_repo.create_or_get_conversation(workspace_id, user_id, thread_id, "Test Chat")
        print(f"Created Conversation: {conv.id}")
        
        await conv_repo.save_message(conv.id, "user", "Hello Swarm!", {"sender_id": user_id})
        await conv_repo.save_message(conv.id, "agent", "Hello User, I am the Swarm.", {"sender_name": "Strategist"})
        
        messages = await conv_repo.get_messages(conv.id)
        print(f"Retrieved {len(messages)} messages.")
        for msg in messages:
            print(f" - [{msg.sender_type}] {msg.content}")
            
        assert len(messages) == 2
        assert messages[0].content == "Hello Swarm!"

        # 2. Test Workflow Engine Integration (Mocked Swarm)
        # We'll check if run() correctly hits the conversation tables
        print("\n2. Testing SwarmWorkflowEngine Integration (Setup)...")
        registry = MockRegistry()
        engine_runner = SwarmWorkflowEngine(registry)
        
        # Override Swarm to avoid real LLM calls
        class MockSwarm:
            async def run(self, **kwargs):
                return {"governance": "This is a persistent response."}
        
        engine_runner.swarm = MockSwarm()
        
        new_thread_id = str(uuid.uuid4())
        request = SubmitWorkflowRequest(
            thread_id=new_thread_id,
            session_id=str(uuid.uuid4()),
            tenant_id="test-tenant",
            user_query="Run persistent mission",
            workflow_mode=WorkflowMode.hybrid,
            analysis_mode=AnalysisMode.standard
        )
        # Add mock attributes that would be present in real request
        request.workspace_id = workspace_id
        request.user_id = user_id
        
        print("Running engine_runner.run()...")
        events = []
        async for event in engine_runner.run(session, request):
            events.append(event)
            
        # Verify persistence after run
        # Note: We need a fresh session or refresh because run() commits inside
        await session.close()
        
    async with async_session() as session:
        conv_repo = ConversationRepository(session)
        stmt = select(ConversationRecord).where(ConversationRecord.thread_id == new_thread_id)
        result = await session.execute(stmt)
        persisted_conv = result.scalar_one_or_none()
        
        print(f"\nVerifying Persistence for thread {new_thread_id}...")
        if persisted_conv:
            print(f"Found Conversation ID: {persisted_conv.id}")
            messages = await conv_repo.get_messages(persisted_conv.id)
            print(f"Found {len(messages)} persisted messages.")
            for msg in messages:
                print(f" - [{msg.sender_type}] {msg.content}")
            
            assert len(messages) >= 2 # User query + Agent response
            print("Persistence Test PASSED!")
        else:
            print("FAILED: Conversation not found in DB.")

    await engine.dispose()

if __name__ == "__main__":
    from sqlalchemy import select
    asyncio.run(test_persistence())
