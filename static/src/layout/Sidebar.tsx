import { NavLink, useNavigate } from "react-router-dom";
import { routeMetadata } from "../router/route-metadata";
import { useOrchestratorStore } from "../shared/orchestrator/store";

const navSections = [
  { label: null, groups: ["overview", "workspace"] },
  { label: "Knowledge", groups: ["knowledge"] },
  { label: "System", groups: ["system"] },
] as const;

export function Sidebar(): JSX.Element {
  const navigate = useNavigate();
  const { startNewChat } = useOrchestratorStore();

  async function handleNewChat(): Promise<void> {
    await startNewChat();
    navigate("/chat");
  }

  return (
    <aside className="sidebar-shell" aria-label="Main navigation">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="sidebar-brand__icon">B</div>
        <div className="sidebar-brand__text">
          <span className="sidebar-brand__name">BLAIQ Core</span>
          <span className="sidebar-brand__plan">Enterprise</span>
        </div>
      </div>

      {/* New Chat */}
      <button type="button" className="sidebar-new-chat" onClick={() => void handleNewChat()}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New chat
      </button>

      {/* Navigation */}
      <nav className="sidebar-nav" aria-label="Primary">
        {navSections.map((section) => (
          <div key={section.label ?? "main"} className="sidebar-nav__section">
            {section.label && (
              <p className="sidebar-nav__section-label">{section.label}</p>
            )}
            {routeMetadata
              .filter((item) => {
                const group = item.id === "overview" ? "overview" : item.navGroup;
                return section.groups.some((g) => g === group);
              })
              .map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.id}
                    to={item.path}
                    end={item.path === "/overview"}
                    className={({ isActive }) =>
                      `sidebar-nav__item${isActive ? " is-active" : ""}`
                    }
                  >
                    <Icon width={18} height={18} className="sidebar-nav__icon" />
                    <span className="sidebar-nav__label">{item.label}</span>
                  </NavLink>
                );
              })}
          </div>
        ))}
      </nav>

      {/* Get Started Card */}
      <div className="sidebar-started">
        <p className="sidebar-started__title">Get started</p>
        <div className="sidebar-started__progress">
          <div className="sidebar-started__bar">
            <div className="sidebar-started__fill" style={{ width: "25%" }} />
          </div>
          <span className="sidebar-started__pct">25%</span>
        </div>
        <p className="sidebar-started__hint">Looking good!</p>
      </div>
    </aside>
  );
}
