import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { ArtifactDetailView } from "../features/orchestrator/OrchestratorWorkspace";
import { useOrchestratorStore } from "../shared/orchestrator/store";

export function ArtifactDetailPage() {
  const { threadId = "" } = useParams();
  const { refreshStatus } = useOrchestratorStore();

  useEffect(() => {
    if (!threadId) {
      return;
    }
    void refreshStatus(threadId).catch(() => undefined);
  }, [refreshStatus, threadId]);

  if (!threadId) {
    return <div className="empty-state">Missing thread identifier.</div>;
  }

  return <ArtifactDetailView />;
}
