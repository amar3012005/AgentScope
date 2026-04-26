Kimi Platform — Comprehensive Database Schema Design
Based on full navigation of kimi.com across: Account Settings, Presets/Memory, Chat interface, Kimi+ Marketplace, Agent detail (JoKimi), Model selector, Kimi Code, and Pricing/Subscription tiers.

1. ENTITY RELATIONSHIP OVERVIEW
text
users ─────────────────────────────────────────────────────┐
  │ 1:1   subscriptions                                      │
  │ 1:N   user_memories                                      │
  │ 1:N   user_presets (saved prompts)                       │
  │ 1:N   user_preferences                                   │
  │ 1:N   oauth_identities                                   │
  │ 1:N   chats ──────────────── 1:N messages                │
  │                └── belongs_to kimiplus_agents (optional) │
  │ 1:N   claw_groups ─── N:M claw_agents                    │
  └───────────────────────────────────────────────────────┘

kimiplus_agents ─── 1:N agent_suggested_prompts
                └── 1:N chats (via agent_id FK)
                └── belongs_to users (creator)
                └── has category (Productivity | Lifestyle)

skills ──── N:M chat_skills (per-message tool attachment)
2. DETAILED TABLE SCHEMAS
users
Core identity table. Observed fields from Account Settings.
​

sql
CREATE TABLE users (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  username        VARCHAR(100)  NOT NULL,
  avatar_url      TEXT,
  phone_number    VARCHAR(30)   UNIQUE,
  -- Auth
  email           VARCHAR(255)  UNIQUE,
  -- Preferences (denormalized fast-access)
  theme           VARCHAR(20)   NOT NULL DEFAULT 'system',
                                -- ENUM: 'system' | 'light' | 'dark'
  language        VARCHAR(10)   NOT NULL DEFAULT 'en',
  expand_sidebar_on_search BOOLEAN NOT NULL DEFAULT TRUE,
  memory_enabled  BOOLEAN       NOT NULL DEFAULT TRUE,
  -- Lifecycle
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ   -- soft delete
);
Indexes: idx_users_phone, idx_users_email, idx_users_deleted_at

oauth_identities
Third-party login providers (WeChat, Google observed).
​

sql
CREATE TABLE oauth_identities (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider        VARCHAR(30)   NOT NULL,
                                -- ENUM: 'google' | 'wechat'
  provider_uid    VARCHAR(255)  NOT NULL,
  display_name    VARCHAR(100),
  linked_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  UNIQUE (provider, provider_uid)
);
Index: idx_oauth_user_id, idx_oauth_provider_uid

subscriptions
Pricing tiers observed: Free, Moderato ($19), Allegretto ($39), Allegro ($99), Vivace ($199). Billing cycles: monthly or annual.
​

sql
CREATE TABLE subscriptions (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID          NOT NULL UNIQUE REFERENCES users(id),
  plan            VARCHAR(30)   NOT NULL DEFAULT 'free',
                                -- ENUM: 'free' | 'moderato' | 'allegretto'
                                --       | 'allegro' | 'vivace' | 'business'
  plan_label      VARCHAR(50),  -- e.g., "Advanced Flow", "Pro Choice"
  billing_cycle   VARCHAR(20)   NOT NULL DEFAULT 'monthly',
                                -- ENUM: 'monthly' | 'annual'
  price_cents     INTEGER,      -- stored price in cents at time of subscribe
  status          VARCHAR(20)   NOT NULL DEFAULT 'active',
                                -- ENUM: 'active' | 'cancelled' | 'expired' | 'trial'
  trial_ends_at   TIMESTAMPTZ,  -- "On trial" label observed[screenshot:4]
  current_period_start TIMESTAMPTZ,
  current_period_end   TIMESTAMPTZ,
  -- Feature quotas (track credits)
  agent_credits_used   INTEGER  NOT NULL DEFAULT 0,
  agent_credits_limit  INTEGER,  -- NULL = unlimited
  kimi_code_credits_used   INTEGER NOT NULL DEFAULT 0,
  kimi_code_credits_limit  INTEGER,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
Index: idx_subscriptions_user_id, idx_subscriptions_status

user_memories
From Memory Space settings — Kimi stores long-term preferences from past conversations.
​

sql
CREATE TABLE user_memories (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content         TEXT          NOT NULL,   -- extracted preference/fact
  source_chat_id  UUID          REFERENCES chats(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ   -- individual memory can be deleted
);
Index: idx_user_memories_user_id, idx_user_memories_deleted_at

user_presets (Saved Prompts)
"Presets" system with Trigger Word + Content.
​

sql
CREATE TABLE user_presets (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  trigger_word    VARCHAR(100)  NOT NULL,   -- e.g., "Professional translation"
  content         TEXT          NOT NULL,   -- the full prompt body
  is_random       BOOLEAN       NOT NULL DEFAULT FALSE, -- "Random One" generated
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, trigger_word)
);
Index: idx_user_presets_user_id

kimiplus_agents
The Kimi+ agent/Claw system. Observed fields from JoKimi agent detail and marketplace.

sql
CREATE TABLE kimiplus_agents (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            VARCHAR(100)  UNIQUE NOT NULL, -- URL slug: e.g., 'jokimi'
  name            VARCHAR(100)  NOT NULL,
  description     TEXT,
  avatar_url      TEXT,
  creator_id      UUID          REFERENCES users(id) ON DELETE SET NULL,
  is_official     BOOLEAN       NOT NULL DEFAULT FALSE, -- "From Kimi" official agents
  category        VARCHAR(50),  -- ENUM: 'productivity' | 'lifestyle'
  greeting_message TEXT,        -- initial bot message shown in chat
  model_override  VARCHAR(50),  -- e.g., 'k2.6-instant' (NULL = use chat default)
  -- Status
  status          VARCHAR(20)   NOT NULL DEFAULT 'active',
                                -- ENUM: 'draft' | 'active' | 'archived'
  is_public       BOOLEAN       NOT NULL DEFAULT TRUE,
  -- Plan gating (Kimi Claw Exclusive = allegretto+)
  required_plan   VARCHAR(30),  -- NULL = free, 'allegretto' = gated
  -- Metadata
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
Index: idx_kimiplus_agents_slug, idx_kimiplus_agents_creator_id, idx_kimiplus_agents_category, idx_kimiplus_agents_is_official

agent_suggested_prompts
The clickable example prompts shown in the agent chat.
​

sql
CREATE TABLE agent_suggested_prompts (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        UUID          NOT NULL REFERENCES kimiplus_agents(id) ON DELETE CASCADE,
  prompt_text     TEXT          NOT NULL,
  display_order   SMALLINT      NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
chats
Core conversation container. URL pattern: /chat/{chat_id}. Agent chats: /kimiplus/{agent_slug}.
​

sql
CREATE TABLE chats (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- Optional agent association
  agent_id        UUID          REFERENCES kimiplus_agents(id) ON DELETE SET NULL,
  -- Chat type / mode
  chat_type       VARCHAR(30)   NOT NULL DEFAULT 'standard',
                                -- ENUM: 'standard' | 'agent' | 'agent_swarm'
                                --       | 'deep_research' | 'slides' | 'docs'
                                --       | 'sheets' | 'websites' | 'code'
  model           VARCHAR(50)   NOT NULL DEFAULT 'k2.6-instant',
                                -- 'k2.6-instant' | 'k2.6-thinking' |
                                -- 'k2.6-agent' | 'k2.6-agent-swarm'
  -- Metadata
  title           VARCHAR(500),  -- auto-generated from first message
  status          VARCHAR(20)   NOT NULL DEFAULT 'active',
                                -- ENUM: 'active' | 'archived' | 'deleted'
  -- Claw group association (Kimi Claw)
  claw_group_id   UUID          REFERENCES claw_groups(id) ON DELETE SET NULL,
  -- Attribution / tracking (observed in URL params)
  source          VARCHAR(100), -- e.g., 'kimi_homepage_sidebar'
  track_id        UUID,         -- analytics tracking UUID
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
Index: idx_chats_user_id, idx_chats_agent_id, idx_chats_created_at DESC, idx_chats_deleted_at, idx_chats_claw_group_id

messages
Individual messages within a chat. Supports text, files/photos (observed via "Add files & photos").
​

sql
CREATE TABLE messages (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id         UUID          NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role            VARCHAR(20)   NOT NULL,
                                -- ENUM: 'user' | 'assistant' | 'system' | 'tool'
  content         TEXT,         -- main text content
  -- Tool/skill metadata
  skill_used      VARCHAR(50),  -- e.g., 'deep-research' | 'pdf' | 'docx' | 'xlsx'
                                --       | 'web_search' | 'professional_data'
  -- Web search context
  search_results  JSONB,        -- array of {url, title, snippet} if web_search used
  -- Thinking mode
  thinking_content TEXT,        -- internal reasoning (k2.6-thinking mode)
  -- Status
  status          VARCHAR(20)   NOT NULL DEFAULT 'completed',
                                -- ENUM: 'streaming' | 'completed' | 'error' | 'cancelled'
  -- Token usage
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  -- Ordering
  sequence_number INTEGER       NOT NULL,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
Index: idx_messages_chat_id, idx_messages_chat_sequence (chat_id, sequence_number), idx_messages_role

message_attachments
Files/photos attached to messages (observed: "Add files & photos").
​

sql
CREATE TABLE message_attachments (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id      UUID          NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  file_type       VARCHAR(20)   NOT NULL,
                                -- ENUM: 'image' | 'pdf' | 'docx' | 'xlsx' | 'other'
  file_name       VARCHAR(500)  NOT NULL,
  file_url        TEXT          NOT NULL,   -- storage URL
  file_size_bytes BIGINT,
  mime_type       VARCHAR(100),
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
skills
Built-in tools/capabilities (deep-research, docx, pdf, xlsx, web_search, professional_data observed).
​

sql
CREATE TABLE skills (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            VARCHAR(50)   UNIQUE NOT NULL, -- 'deep-research', 'pdf', 'docx', etc.
  name            VARCHAR(100)  NOT NULL,
  description     TEXT,
  provider        VARCHAR(50)   NOT NULL DEFAULT 'kimi', -- 'kimi' | 'user_custom'
  required_plan   VARCHAR(30),  -- NULL = free
  is_beta         BOOLEAN       NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
claw_groups
Kimi Claw group chats — "Add multiple Claws to group chats and collaborate with members". Observed: "New group" option in sidebar.

sql
CREATE TABLE claw_groups (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id        UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name            VARCHAR(200)  NOT NULL,
  description     TEXT,
  deployment_target VARCHAR(30),
                                -- ENUM: 'cloud' | 'android_local' | 'desktop'
                                -- observed in "One-click deployment"[screenshot:9]
  status          VARCHAR(20)   NOT NULL DEFAULT 'active',
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
claw_group_agents
Many-to-many: which agents belong to a Claw group.

sql
CREATE TABLE claw_group_agents (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id        UUID          NOT NULL REFERENCES claw_groups(id) ON DELETE CASCADE,
  agent_id        UUID          NOT NULL REFERENCES kimiplus_agents(id) ON DELETE CASCADE,
  added_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  UNIQUE (group_id, agent_id)
);
claw_group_members
Collaboration — members in a Claw group.
​

sql
CREATE TABLE claw_group_
