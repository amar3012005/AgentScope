import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./TopBar";
import { useOrchestratorStore } from "../shared/orchestrator/store";

export function AppShell(): JSX.Element {
  const location = useLocation();
  const { state } = useOrchestratorStore();
  const hasConversation = state.messages.length > 0 || Boolean(state.threadId);
  const isChatRoute = location.pathname === "/chat";
  const isFocusShell = isChatRoute && !hasConversation;

  return (
    <div className={`app-shell ${isFocusShell ? "app-shell--focus" : ""}`}>
      {!isFocusShell ? <Sidebar /> : null}
      <div className="app-shell__main">
        {!isFocusShell ? <Topbar /> : null}
        <main className="app-shell__content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
