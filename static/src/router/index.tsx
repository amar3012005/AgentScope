import { Navigate, Route, Routes } from "react-router-dom";
import { OrchestratorStoreProvider } from "../shared/orchestrator/store";
import { AppShell } from "../layout/AppShell";
import { OverviewPage } from "../pages/OverviewPage";
import { ChatPage } from "../pages/ChatPage";
import { WorkflowsPage } from "../pages/WorkflowsPage";
import { RunDetailPage } from "../pages/RunDetailPage";
import { ArtifactsPage } from "../pages/ArtifactsPage";
import { ArtifactDetailPage } from "../pages/ArtifactDetailPage";
import { UploadsPage } from "../pages/UploadsPage";
import { AgentsPage } from "../pages/AgentsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { NotFoundPage } from "../pages/NotFoundPage";

export function AppRoutes() {
  return (
    <OrchestratorStoreProvider>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route element={<AppShell />}>
          <Route path="/overview" element={<OverviewPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/runs/:threadId" element={<RunDetailPage />} />
          <Route path="/artifacts" element={<ArtifactsPage />} />
          <Route path="/artifacts/:threadId" element={<ArtifactDetailPage />} />
          <Route path="/uploads" element={<UploadsPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </OrchestratorStoreProvider>
  );
}
