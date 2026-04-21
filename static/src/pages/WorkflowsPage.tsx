import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PageFrame } from "../layout/PageFrame";
import { useOrchestratorStore } from "../shared/orchestrator/store";

function normalizeThreadId(workflowId: string): string {
  return workflowId.startsWith("blaiq-") ? workflowId.slice("blaiq-".length) : workflowId;
}

export function WorkflowsPage(): JSX.Element {
  const { state, refreshWorkflows } = useOrchestratorStore();

  useEffect(() => {
    void refreshWorkflows().catch(() => undefined);
  }, [refreshWorkflows]);

  return (
    <PageFrame
      eyebrow="Workflow ledger"
      title="Every orchestration run in one place."
      description="Review status, jump into run detail, or open the final Vangogh artifact when a workflow has completed."
    >
      <section className="page-frame__panel">
        <div className="page-frame__panel-label">Recent threads</div>
        <div className="page-frame__list">
          {state.workflows.length === 0 ? (
            <div className="page-frame__list-item">
              <div className="page-frame__route-copy">
                <p className="page-frame__list-title">No workflow history yet</p>
                <p className="page-frame__list-copy">Submit a workflow from the chat workspace to populate this view.</p>
              </div>
            </div>
          ) : (
            state.workflows.map((workflow, index) => {
              const threadId = normalizeThreadId(workflow.workflow_id);
              return (
                <article key={workflow.workflow_id} className="page-frame__list-item page-frame__list-item--stacked">
                  <div className="page-frame__route-copy">
                    <div className="page-frame__workflow-head">
                      <span className="page-frame__route-index">{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <p className="page-frame__list-title">{threadId}</p>
                        <p className="page-frame__list-copy">Run {workflow.run_id || "pending"}</p>
                      </div>
                    </div>
                    <p className="page-frame__list-copy">Started {workflow.start_time || "unknown time"}</p>
                  </div>
                  <div className="page-frame__workflow-actions">
                    <span className="page-frame__status-pill">{workflow.status}</span>
                    <Link className="page-frame__button" to={`/runs/${threadId}`}>Open run</Link>
                    <Link className="page-frame__button page-frame__button--primary" to={`/artifacts/${threadId}`}>Artifact</Link>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </section>
    </PageFrame>
  );
}
