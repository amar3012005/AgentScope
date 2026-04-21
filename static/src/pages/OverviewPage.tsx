import { Link } from "react-router-dom";
import { PageFrame } from "../layout/PageFrame";
import { useOrchestratorStore } from "../shared/orchestrator/store";

export function OverviewPage() {
  const { state } = useOrchestratorStore();
  const completed = state.workflows.filter((workflow) => workflow.status.toLowerCase().includes("complete")).length;
  const blocked = state.workflows.filter((workflow) => workflow.status.toLowerCase().includes("block")).length;

  return (
    <PageFrame
      eyebrow="Control room"
      title="Production-grade orchestration workspace."
      description="The frontend is now organized around the actual BLAIQ workflow model: conversation, execution timeline, HITL pause and resume, governance, schema edits, uploads, agents, and Vangogh artifacts."
      actions={
        <>
          <Link className="page-frame__button" to="/workflows">Open workflows</Link>
          <Link className="page-frame__button page-frame__button--primary" to="/chat">Open workspace</Link>
        </>
      }
    >
      <div className="page-frame__grid page-frame__grid--overview">
        <section className="page-frame__panel page-frame__panel--hero">
          <p className="page-frame__panel-label">Primary UX surface</p>
          <h2 className="page-frame__panel-title">One workspace for chat, orchestration, and preview.</h2>
          <p className="page-frame__panel-copy">
            The main chat route is where users submit requests, follow live workflow state, answer HITL prompts, inspect governance, and preview Vangogh output without context switching.
          </p>
          <div className="page-frame__tag-list">
            <span className="page-frame__tag">SSE</span>
            <span className="page-frame__tag">HITL</span>
            <span className="page-frame__tag">Governance</span>
            <span className="page-frame__tag">Schema regen</span>
          </div>
        </section>
        <section className="page-frame__panel page-frame__panel--soft">
          <p className="page-frame__panel-label">Metrics</p>
          <div className="page-frame__metrics">
            <div className="page-frame__metric">
              <p className="page-frame__metric-label">Tracked workflows</p>
              <p className="page-frame__metric-value">{state.workflows.length}</p>
            </div>
            <div className="page-frame__metric">
              <p className="page-frame__metric-label">Completed</p>
              <p className="page-frame__metric-value">{completed}</p>
            </div>
            <div className="page-frame__metric">
              <p className="page-frame__metric-label">Blocked on user</p>
              <p className="page-frame__metric-value">{blocked}</p>
            </div>
          </div>
        </section>
        <section className="page-frame__panel">
          <p className="page-frame__panel-label">Dashboard sections</p>
          <div className="page-frame__route-list">
            {[
              ["Chat workspace", "Primary page with transcript, composer, timeline, preview, schema, and governance."],
              ["Workflows", "Recent thread ledger with direct run and artifact navigation."],
              ["Artifacts", "Completed Vangogh previews grouped by workflow completion."],
              ["Uploads", "Knowledge ingestion entry point for GraphRAG-ready content."],
              ["Agents", "Live registry of orchestrator-connected agents and capabilities."],
            ].map(([label, description], index) => (
              <div key={label} className="page-frame__route-card">
                <span className="page-frame__route-index">{String(index + 1).padStart(2, "0")}</span>
                <div className="page-frame__route-copy">
                  <p className="page-frame__route-label">{label}</p>
                  <p className="page-frame__route-description">{description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </PageFrame>
  );
}
