import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PageFrame } from "../layout/PageFrame";
import { useOrchestratorStore } from "../shared/orchestrator/store";

function normalizeThreadId(workflowId: string): string {
  return workflowId.startsWith("blaiq-") ? workflowId.slice("blaiq-".length) : workflowId;
}

export function ArtifactsPage(): JSX.Element {
  const { state, refreshWorkflows } = useOrchestratorStore();

  useEffect(() => {
    void refreshWorkflows().catch(() => undefined);
  }, [refreshWorkflows]);

  const candidateWorkflows = state.workflows.filter((workflow) => workflow.status.toLowerCase().includes("complete"));

  return (
    <PageFrame
      eyebrow="Vangogh output"
      title="Artifact previews tied directly to workflow history."
      description="Completed runs surface their preview route here so the user can move from orchestration to rendered output without losing context."
    >
      <section className="page-frame__panel">
        <div className="page-frame__panel-label">Rendered outputs</div>
        <div className="page-frame__list">
          {candidateWorkflows.length === 0 ? (
            <div className="page-frame__list-item">
              <div className="page-frame__route-copy">
                <p className="page-frame__list-title">No completed artifacts yet</p>
                <p className="page-frame__list-copy">Complete a creative workflow and the Vangogh artifact route will appear here.</p>
              </div>
            </div>
          ) : (
            candidateWorkflows.map((workflow) => {
              const threadId = normalizeThreadId(workflow.workflow_id);
              return (
                <article key={workflow.workflow_id} className="page-frame__list-item page-frame__list-item--stacked">
                  <div className="page-frame__route-copy">
                    <p className="page-frame__list-title">Artifact for {threadId}</p>
                    <p className="page-frame__list-copy">Completed at {workflow.start_time || "unknown time"}</p>
                  </div>
                  <div className="page-frame__workflow-actions">
                    <Link className="page-frame__button" to={`/runs/${threadId}`}>Run detail</Link>
                    <Link className="page-frame__button page-frame__button--primary" to={`/artifacts/${threadId}`}>Open preview</Link>
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
