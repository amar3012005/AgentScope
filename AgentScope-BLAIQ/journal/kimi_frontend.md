Kimi.com Product Reverse-Engineering Analysis
All conclusions labeled: [Observed] / [Inferred] / [Unknown]
Evidence: Screenshots, nav traversal, DOM inspection, login-wall trigger test, API platform review.

TASK 1: Full UX Surface Inventory
1A. Sitemap of Visible App Surfaces
Surface	URL	Entry Point	Auth Required	Status
Home / New Chat	kimi.com/	Direct	No (gated on submit)	GA [Observed]
Slides	kimi.com/slides	Sidebar	No (gated on submit)	GA [Observed]
Websites	kimi.com/websites	Sidebar	No (gated on submit)	GA [Observed]
Docs	kimi.com/docs	Sidebar	No (gated on submit)	GA [Observed]
Deep Research	kimi.com/deep-research	Sidebar	No (gated on submit)	GA [Observed]
Sheets	kimi.com/sheets	Sidebar	No (gated on submit)	GA [Observed]
Agent Swarm	kimi.com/agent-swarm	Sidebar	No (gated on submit)	Beta [Observed]
Kimi Code (marketing)	kimi.com/code	Sidebar	No	GA [Observed]
Kimi Code CLI/Console	code.kimi.com	Kimi Code page	Yes	GA [Observed]
Kimi Claw	kimi.com/?claw	Sidebar (Beta)	No (gated on submit)	Beta [Observed]
Chat History	Sidebar section	Sidebar	Yes	[Observed]
Get App	kimi.com/app	Sidebar	No	GA [Observed]
Login Modal	Overlay	On chat submit	No	[Observed]
API Platform	platform.moonshot.cn / platform.kimi.com	External	Yes	GA [Observed]
API Docs / Pricing	platform.kimi.com/docs/pricing/chat	API Platform	No	GA [Observed]
1B. Primary Navigation Model
Element	Type	Position	Behavior
Sidebar (left panel, ~235px)	Persistent vertical nav	Left	Collapsible via toggle icon [Observed]
Logo / Home	Navigation item	Sidebar top	Click = Home [Observed]
Mode selector (New Chat, Slides, Websites, etc.)	Route-based nav	Sidebar	Click routes to mode-specific compose surface [Observed]
Agent Swarm, Kimi Claw	Beta badges	Sidebar	Same routing pattern [Observed]
Chat History	Accordion section	Sidebar lower	Requires auth to sync; shows "Log in to sync" for guests [Observed]
Get App	CTA item	Sidebar bottom	Leads to app download [Observed]
Log In	Dropdown / CTA	Sidebar bottom	Expands auth options [Observed]
Sidebar collapse	Icon button	Sidebar top-right	Collapses sidebar to icon-only rail [Observed]
1C. Key User Journeys
Journey	Steps (Observed)	Gate Points
New Chat	Land on / → type in composer → click submit → login modal appears → auth → chat opens	Login on first submit [Observed]
Tool Use (Agent mode)	Select Agent chip in composer → write query → submit → login gate → post-auth: agent executes tools	Login [Observed]; tool execution flow [Inferred post-auth]
File Upload	Click + in composer → select "Add files & photos" → file picker → attach → query	Login required to submit [Observed]
Slides creation	Navigate /slides → select style/template tabs → write prompt → "Agent|Slides" chip visible → submit	Style/template picker [Observed]; generation phase [Inferred]
Websites creation	Navigate /websites → select template → "Agent|Websites" chip → write prompt → submit	[Observed]; render [Inferred]
Docs task	Navigate /docs → "Agent|Docs" chip → featured cases shown → write prompt	[Observed]
Deep Research	Navigate /deep-research → "Agent|Deep Research" chip → featured cases shown → submit	[Observed]; multi-source retrieval [Inferred]
Sheets analysis	Navigate /sheets → "Agent|Sheets" chip → featured cases → submit	[Observed]
Agent Swarm	Navigate /agent-swarm → "Agent Swarm" chip, model says "K2.6 Agent Swarm" → submit	Parallel sub-agent execution [Inferred]
Chat History	Sidebar → Chat History section → "Log in to sync chat history" prompt	[Observed]
Settings	Not publicly visible as separate page; [Unknown] post-auth	
Kimi Code CLI	code.kimi.com → curl -L code.kimi.com/install.sh | bash → CLI tool in terminal	External CLI [Observed]
1D. Chat Session State Machine
text
[IDLE / Composer open]
        │
        ▼ user types query
[INPUT FILLED]
        │
        ▼ user clicks submit (unauthenticated)
[LOGIN GATE] ──── auth cancel ──► [IDLE]
        │
        ▼ auth success
[SUBMITTING / Processing]
        │
        ├──► [STREAMING - LLM tokens arriving]
        │         │
        │         ├──► [TOOL_CALL - agent invokes tool]
        │         │         │
        │         │         ▼
        │         │    [TOOL_WAITING - awaiting tool result] [Inferred]
        │         │         │
        │         │         ▼
        │         │    [TOOL_RESULT - artifact rendered] [Inferred]
        │         │         │
        │         │         ▼
        │         └──► [STREAMING resumed]
        │
        ├──► [COMPLETE - full response shown]
        │         │
        │         ▼
        │    [IDLE - follow-up composer active]
        │
        └──► [FAILED / ERROR] [Inferred - not triggered in session]
                  │
                  ▼
             [RETRY option shown] [Inferred]
State	Trigger	Visual Signal
IDLE	Page load / new chat	Composer with placeholder "Ask Anything..." [Observed]
INPUT FILLED	Typing	Send button activates (arrow turns teal) [Observed]
LOGIN GATE	Unauthenticated submit	Modal overlay with Google / Phone auth [Observed]
SUBMITTING	Post-auth submit	Send button transitions to spinner [Inferred]
STREAMING	LLM generating	Token-by-token text appearance [Inferred]
TOOL_CALL	Agent activates tool	Tool invocation label shown inline [Inferred]
TOOL_WAITING	Awaiting tool return	Progress/loading indicator [Inferred]
COMPLETE	Stream ends	Full message, copy/share actions appear [Inferred]
FAILED	Network/API error	Error message with retry [Inferred]
1E. Trust Signals
Signal Type	Implementation	Location	Status
Model version label	"K2.6 Instant / Thinking / Agent / Agent Swarm" visible in picker	Composer bar	Observed
Beta badge	Blue "Beta" chip on Agent Swarm, Kimi Claw	Sidebar items	Observed
Agent mode chip	"Agent | [Mode]" colored pill in composer	Composer toolbar	Observed
Login requirement	Forces auth before any data is sent	Modal overlay	Observed
Terms/Privacy at login	Linked text below auth buttons	Login modal	Observed
Featured cases (social proof)	Curated example outputs on mode landing pages	Mode home screens	Observed
Source citations (in answers)	Not directly observable (pre-auth)	Chat messages	Inferred (known feature)
API pricing transparency	Token-by-token billing, public pricing page	platform.kimi.com	Observed
K2.6 announcement banner	"K2.6 official version is now updated"	Kimi Code page / API platform	Observed
TASK 2: Interaction & Orchestration Extraction
Query Used
"Compare the AI chip landscape in 2025: NVIDIA H100 vs AMD MI300X vs Google TPU v5 — include market share, benchmark performance, and enterprise adoption trends"

2A. Sequence Diagram (Text)
text
User                    Kimi Frontend            Auth Layer           Orchestrator         Tools
 |                           |                       |                     |                 |
 |── type query ────────────►|                       |                     |                 |
 |                           |── send button active  |                     |                 |
 |── click submit ──────────►|                       |                     |                 |
 |                           |── check auth ────────►|                     |                 |
 |                           |                       |── not authed        |                 |
 |                           |◄── show login modal ──|                     |                 |
 |── user cancels ──────────►|                       |                     |                 |
 |                           |── [session ends here for unauthenticated]   |                 |
 |                                                                          |                 |
 [IF AUTHENTICATED — inferred from observed modal + product docs]
 |── auth complete ──────────►|                      |                     |                 |
 |                            |── POST /chat ────────────────────────────►|                 |
 |                            |                      |                     |── plan query    |
 |                            |                      |                     |── invoke web    |
 |                            |                      |                     |   search ──────►|
 |                            |                      |                     |◄── results ─────|
 |                            |                      |                     |── synthesize    |
 |                            |◄── SSE stream ──────────────────────────── |                 |
 |◄── token-by-token text ────|                      |                     |                 |
 |◄── citations appended ─────|                      |                     |                 |
 |◄── COMPLETE signal ────────|                      |                     |                 |
2B. Event Timeline with Timestamps
T+ (sec)	Phase	Visible Event	Evidence
0.0	Compose	Composer active, "Ask Anything..."	Observed 
~0.5	Input	User text appears in composer, send button activates (teal)	Observed 
~1.0	Submit	Click send → spinner transition	Observed
~1.5	Auth gate	Login modal overlays full screen	Observed 
~1.5	Auth gate	Google OAuth + Phone options shown	Observed 
Auth duration	Auth	User completes OAuth flow	[Inferred; not completed]
Auth+~0.3s	Routing	POST request to chat API	[Inferred]
Auth+~1-3s	Orchestration	For Agent mode: query analysis, tool planning	[Inferred]
Auth+~2-8s	Streaming	SSE/chunked stream begins, tokens appear	[Inferred]
Auth+~5-30s	Tool calls	Web search, file reads, sub-agent calls	[Inferred for Agent mode]
Completion	Done	Full response, action bar (copy/share/retry)	[Inferred]
2C. Inferred Orchestration Pattern
Dimension	Assessment	Confidence
Pattern type	Planner-Worker hybrid: central LLM (K2.6) acts as planner; specialized agents (Slides, Docs, Research, Swarm) are workers	75%
Agent Swarm	Explicit parallel multi-agent; K2.6 Agent Swarm label in model picker; described as "Large-scale search, long-form writing, batch tasks"	85%
Tool call visibility	Likely shown inline as collapsible "thinking" or tool-call blocks (per industry pattern and Kimi Claw browser agent)	65%
Retry/failure	Likely auto-retry with exponential backoff; no visible retry UI observed pre-auth	Unknown
Clarification loops	Not observed; query was accepted as-is with no clarification prompt before auth gate	Observed (no loop pre-auth)
Intermediate artifacts	Mode-specific: Slides/Sheets/Websites produce structured artifacts (HTML, PPTX-equivalent); streamed to canvas panel	Inferred
TASK 3: Network Behavior Mapping
All observations are from public page inspection and browser network tab visibility during unauthenticated use. No auth tokens inspected.

3A. Endpoint Groups by Function
Group	Base Domain	Observable Path Pattern	Method	Inferred Function
Chat completion	api.moonshot.cn or internal	/v1/chat/completions	POST	LLM streaming responses [Inferred from API docs]
Session management	kimi.com backend	/api/session/* or /api/chat/*	GET/POST	Create, resume, list sessions [Inferred]
File upload	kimi.com backend	/api/files/upload	POST multipart	Attachment ingestion [Inferred from "Add files" UX]
Web search tool	Internal or proxied	Tool call within LLM stream	—	Real-time web retrieval for Agent mode [Inferred]
Authentication	kimi.com auth	OAuth2 redirect / OTP flow	POST/GET	Google OAuth, phone OTP (+86 default) [Observed]
Chat history	kimi.com backend	/api/history/* or /api/conversations	GET	Sync history post-auth [Observed: "Log in to sync"]
Mode routing	Client-side	React Router to /slides, /docs, etc.	—	Frontend SPA routing [Inferred from instant transitions]
API platform	platform.kimi.com	/docs/*, /pricing/*	GET	Developer docs; billing [Observed]
CLI install	code.kimi.com	/install.sh	GET	Shell script installer [Observed]
3B. Request/Response Schema Shape
Endpoint Type	Request Shape (High-Level)	Response Shape	Notes
Chat completion	{model, messages:[{role,content}], stream:true, tools:[...]}	SSE stream: data: {"id","object","choices":[{"delta":{"content":...}}]}	Standard OpenAI-compatible schema [Inferred from API docs]
File upload	multipart/form-data: {file, purpose}	{file_id, name, size, status}	[Inferred from "files free" pricing note]
Session create	{title?, mode?, agent_type?}	{session_id, created_at}	[Inferred]
Auth (phone OTP)	{phone, country_code, verification_code}	{token, user_id, expires_at}	+86 default observed [Observed]
Auth (Google)	OAuth2 PKCE redirect		
create a dedicated readme folder with all information
Completed 4 steps



about



