import { useEffect, useState } from "react";
import { PageFrame } from "../layout/PageFrame";
import { apiGet } from "../api/client";

interface AgentRecord {
  name: string;
  protocol: string;
  base_url?: string | null;
  supports_stream: boolean;
  capabilities: string[];
  connected_ws: boolean;
  timeout_seconds: number;
  is_live?: boolean;
  ws_live?: boolean;
  rest_live?: boolean;
  rest_error?: string | null;
}

function inferRoutingRole(agent: AgentRecord): string {
  const capabilities = new Set(agent.capabilities.map((capability) => capability.toLowerCase()));
  if (capabilities.has("content_creation") || capabilities.has("gap_analysis")) {
    return "Content generation path";
  }
  if (capabilities.has("graphrag") || capabilities.has("history") || capabilities.has("stream")) {
    return "Evidence retrieval path";
  }
  if (capabilities.has("utility")) {
    return "Utility fallback path";
  }
  return "Generic routing candidate";
}

export function AgentsPage(): JSX.Element {
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void Promise.all([apiGet("/api/v4/agents"), apiGet("/agents/live")])
      .then(async ([registryResponse, liveResponse]) => {
        const registryPayload = (await registryResponse.json()) as { agents?: AgentRecord[] };
        const livePayload = (await liveResponse.json()) as { agents?: AgentRecord[] };

        const liveMap = new Map<string, AgentRecord>(
          (livePayload.agents ?? []).map((agent) => [agent.name, agent])
        );
        const merged = (registryPayload.agents ?? []).map((agent) => {
          const live = liveMap.get(agent.name);
          return {
            ...agent,
            is_live: Boolean(live?.is_live),
            ws_live: Boolean(live?.ws_live),
            rest_live: Boolean(live?.rest_live),
            rest_error: live?.rest_error ?? null,
          };
        });
        setAgents(merged);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load agents"));
  }, []);

  return (
    <PageFrame
      eyebrow="Runtime topology"
      title="Registered agents and their live capabilities."
      description="This page exposes the active agent network behind the orchestration dashboard so workflow execution and routing are visible from the UI."
    >
      <section className="page-frame__panel">
        <div className="page-frame__panel-label">Agent registry cards (Core view)</div>
        <div className="agents-grid">
          {error ? (
            <div className="agents-card">
              <div className="agents-card__head">
                <p className="page-frame__list-title">Unable to load agents</p>
                <span className="agents-status agents-status--offline">error</span>
              </div>
              <p className="page-frame__list-copy">{error}</p>
            </div>
          ) : null}
          {agents.map((agent) => (
            <article key={agent.name} className="agents-card">
              <div className="agents-card__head">
                <p className="page-frame__list-title">{agent.name}</p>
                <span className={`agents-status ${agent.is_live ? "agents-status--live" : "agents-status--offline"}`}>
                  {agent.is_live ? "live" : "offline"}
                </span>
              </div>
              <p className="page-frame__list-copy">{agent.base_url || "WebSocket-only agent"}</p>
              <div className="agents-card__meta">
                <span className="page-frame__tag">{agent.protocol}</span>
                <span className="page-frame__tag">{agent.supports_stream ? "stream" : "sync"}</span>
                <span className="page-frame__tag">{agent.connected_ws ? "ws" : "no-ws"}</span>
                <span className="page-frame__status-pill">{agent.timeout_seconds}s timeout</span>
              </div>
              <div className="agents-card__planning">
                <span className="agents-card__planning-label">Core planning role</span>
                <strong className="agents-card__planning-value">{inferRoutingRole(agent)}</strong>
              </div>
              <div className="agents-card__caps">
                {agent.capabilities.length === 0 ? (
                  <span className="agents-capability-chip agents-capability-chip--muted">No capabilities declared</span>
                ) : (
                  agent.capabilities.map((capability) => (
                    <span key={`${agent.name}-${capability}`} className="agents-capability-chip">
                      {capability}
                    </span>
                  ))
                )}
              </div>
              {!agent.is_live && agent.rest_error ? (
                <p className="agents-card__error">Health probe: {agent.rest_error}</p>
              ) : null}
              <div className="agents-card__transport">
                <span>REST: {agent.rest_live ? "up" : "down"}</span>
                <span>WS: {agent.ws_live ? "up" : "down"}</span>
              </div>
            </article>
          ))}
          {!error && agents.length === 0 ? (
            <div className="agents-card">
              <p className="page-frame__list-title">No registered agents</p>
              <p className="page-frame__list-copy">The core endpoint returned an empty registry.</p>
            </div>
          ) : null}
        </div>
      </section>
    </PageFrame>
  );
}
