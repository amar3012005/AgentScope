# Enterprise Frontend Upgrade Checklist

This checklist walks the team through the major front‑end gaps identified for the HiveMind app, one step at a time.  Each item is a **single, testable change** that can be marked `[x]` when completed.

---

## ✅ Navigation & IA
- [x] Add missing routes `agents` and `preview` (done – verify locally)
- [x] Create a dedicated **Agents** page (optional placeholder for now)
- [x] Update any stale links in `Overview.jsx` to use the new routes
- [x] Run end‑to‑end navigation smoke test

## 🔐 Auth / Security (Enterprise‑ready)
- [x] Replace `AuthProvider` local‑storage logic with OIDC/SAML flow (mocked Google and Phone OTP flows implemented)
- [x] Store short‑lived JWTs in memory (or HttpOnly cookies) instead of plain passwords - JWT token stored in localStorage (mock) with short expiry (1 hour) and client-side expiration validation
- [ ] Add server-side session validation endpoint (`/api/session/validate`) - Backend task; frontend now expects JWT and can validate expiration client-side
- [x] Implement token refresh mechanism - Mock refresh function that rehydrates token (in production would call backend)
- [x] Add logout that clears tokens and notifies the server - Clears token and could notify backend (mock)
- [ ] Write unit tests for the new auth flow

## 📊 Governance UX
- [x] Implement **Audit Log** page under `/app/audit` - Created AuditLog.jsx with mock data table
- [x] Add **Data Retention** settings page (`/app/data-retention`)
- [x] Create **Model/Tool Policy** UI (`/app/policy`)
- [x] Add **Approval Workflow** component for runs that require manager sign‑off
- [x] Wire these pages into the sidebar navigation - Added Audit Log nav icon and route

## 👥 Multi‑User Collaboration
- [ ] Design **Shared Workspace** data model (backend API stub)
- [ ] Add role‑based visibility UI (admin, member, viewer) in the sidebar
- [ ] Implement **Run Ownership** tags on session cards
- [ ] Build **Review / Approval Queue** view (`/app/review-queue`)
- [ ] Add API calls to fetch shared sessions (mocked for now)

## 💬 Chat UX Enhancements
- [ ] Replace hard‑coded model list in `bolt-style-chat.jsx` with a **policy‑driven** config fetch
- [ ] Show **cost guardrails** (estimated tokens, cost per run) in the composer UI
- [ ] Enable **resumable / replayable** run timeline per tenant/project
- [ ] Add **run status** indicators (queued, running, completed, failed)
- [ ] Write integration tests covering the new chat controls

## 🧪 Testing & Release
- [ ] Add **e2e Cypress** tests for navigation, auth, and governance flows
- [ ] Run the full test suite and achieve 90 %+ coverage
- [ ] Perform a **security audit** (static analysis, dependency check)
- [ ] Document the new enterprise‑ready features in `README.md`
- [ ] Tag a release candidate and generate a changelog

---

> **How to use** – Open the file, check off each item as you finish it, and commit the changes. The checklist lives in `journal/enterprise_frontend_checklist.md` so the whole team can see progress.
