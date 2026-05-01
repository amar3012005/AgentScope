# Session Persistence Refactor Plan (PostgreSQL over HIVEMIND)

## 1. Goal
Move from volatile `localStorage` and complex HiveMind state to direct persistence in the PostgreSQL `conversations` and `conversation_messages` tables.

## 2. Completed Backend Changes
- [x] **Repository**: Created `ConversationRepository` in `repositories.py` with methods for `create_or_get_conversation`, `save_message`, `get_messages`, and `list_conversations`.
- [x] **API Endpoints**: Added standard REST routes in `main.py`:
  - `GET /api/v1/conversations`: List user sessions.
  - `POST /api/v1/conversations`: Initialize/Create session.
  - `GET /api/v1/conversations/{id}`: Fetch session history (messages).
  - `POST /api/v1/conversations/{id}/messages`: Append persistent message.
  - `PATCH /api/v1/conversations/{id}`: Rename session.
- [x] **Swarm Integration**: Updated `SwarmWorkflowEngine.run` to:
  - Synchronously create `ConversationRecord` on run initialization.
  - Save the user's query as the first message.
  - Save the swarm's final response as the second message upon completion.

## 3. Frontend Integration (In Progress)
- [x] **Client Update**: Added `listConversations`, `getConversation`, and `updateConversationTitle` to `blaiq-client.js`.
- [ ] **Context Update**: Refactor `BlaiqWorkspaceProvider` to:
  - Replace `localStorage` sync with API calls to the new conversation endpoints.
  - Load full message history from the DB when `sessionId` changes.
  - Sync "Public" chat messages to the DB while keeping technical "thoughts" in the local stream only.

## 4. Next Steps
1. Refactor `BlaiqWorkspaceProvider` to use DB persistence.
2. Update `chatStore.js` if it is still being used by components (currently `BlaiqWorkspaceProvider` seems to be the main state manager).
3. Verify Artifact rendering from DB-stored `thread_id`.
