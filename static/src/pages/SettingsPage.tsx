import { CONFIG } from "../config";
import { useOrchestratorStore } from "../shared/orchestrator/store";

export function SettingsPage() {
  const { state } = useOrchestratorStore();
  return (
    <div className="detail-grid">
      <section className="panel-card">
        <div className="panel-card__header">
          <span>Environment</span>
        </div>
        <dl className="settings-grid">
          <div>
            <dt>Tenant</dt>
            <dd>{state.tenantId}</dd>
          </div>
          <div>
            <dt>API base</dt>
            <dd>{CONFIG.API_BASE || "same-origin"}</dd>
          </div>
          <div>
            <dt>API key transport</dt>
            <dd>{CONFIG.API_KEY ? "X-API-Key configured" : "No client key configured"}</dd>
          </div>
          <div>
            <dt>Session</dt>
            <dd>{state.sessionId}</dd>
          </div>
          <div>
            <dt>Workflow mode</dt>
            <dd>{state.workflowMode}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
