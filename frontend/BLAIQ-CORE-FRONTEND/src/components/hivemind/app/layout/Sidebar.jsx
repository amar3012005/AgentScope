import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  ChevronDown,
  Clock,
  Compass,
  FolderOpen,
  Gift,
  Home,
  LayoutGrid,
  Moon,
  Search,
  Sparkles,
  Star,
  Sun,
  Users,
  Zap,
} from 'lucide-react';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';

const mainNav = [
  { to: '/app/chat', label: 'Home', icon: Home },
  { to: '/app/knowledge', label: 'Search', icon: Search },
];

const projectNav = [
  { to: '/app/overview', label: 'Recent', icon: Clock },
  { to: '/app/agents', label: 'Agents', icon: FolderOpen },
  { to: '/app/preview', label: 'Starred', icon: Star },
  { to: '/app/settings', label: 'Shared with me', icon: Users },
];

const resourceNav = [
  { to: '#discover', label: 'Discover', icon: Compass },
  { to: '#templates', label: 'Templates', icon: LayoutGrid },
];

const integrationNav = [
  { to: '/app/hivemind', label: 'HiveMind', icon: Zap },
];

function NavItem({ to, label, icon: Icon, isDayMode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition-colors ${
          isActive
            ? isDayMode
              ? 'bg-[#F95C4B]/10 text-[#F95C4B] font-medium'
              : 'bg-[#1f1f1f] text-[#F6F4F1]'
            : isDayMode
              ? 'text-[#525252] hover:bg-[#E4DED2]/60 hover:text-[#000]'
              : 'text-[#a1a1a1] hover:bg-[#151515] hover:text-[#d4d4d4]'
        }`
      }
    >
      <Icon size={16} strokeWidth={1.8} />
      {label}
    </NavLink>
  );
}

function SectionLabel({ children, isDayMode }) {
  return (
    <div className={`mb-1 mt-6 px-3 text-[11px] font-medium uppercase tracking-wider ${isDayMode ? 'text-[#9a9a9a]' : 'text-[#525252]'}`}>
      {children}
    </div>
  );
}

export default function Sidebar() {
  const { resetWorkspace, isDayMode, toggleDayMode } = useBlaiqWorkspace();
  const [orgName, setOrgName] = React.useState('BLAIQ Studio');

  React.useEffect(() => {
    // Fetch HiveMind organization info
    const fetchOrgInfo = async () => {
      try {
        const response = await fetch('/api/v1/hivemind/org-info', {
          headers: { Accept: 'application/json' },
        });
        if (response.ok) {
          const data = await response.json();
          if (data.org_name && data.org_name !== 'Unknown Organization') {
            setOrgName(data.org_name);
          }
        }
      } catch (error) {
        console.error('Failed to fetch org info:', error);
      }
    };
    fetchOrgInfo();
  }, []);

  const d = isDayMode;

  return (
    <aside
      className={`flex h-full w-[240px] flex-shrink-0 flex-col border-r ${
        d
          ? 'border-[#E4DED2] bg-[#F6F4F1]/80 backdrop-blur-xl'
          : 'border-[#1e1e1e] bg-[#0a0a0a]/80 backdrop-blur-xl'
      }`}
    >
      {/* Workspace selector */}
      <div className={`flex items-center gap-2.5 border-b px-4 py-3.5 ${d ? 'border-[#E4DED2]' : 'border-[#1e1e1e]'}`}>
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#F95C4B] to-[#ff8a7a] text-[11px] font-bold text-white">
          B
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-between">
          <span className={`truncate text-[13px] font-semibold ${d ? 'text-[#000]' : 'text-[#F6F4F1]'}`}>
            {orgName}
          </span>
          <ChevronDown size={14} className={d ? 'text-[#9a9a9a]' : 'text-[#525252]'} />
        </div>
      </div>

      {/* Main navigation */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <nav className="space-y-0.5">
          {mainNav.map((item) => (
            <NavItem key={item.to} {...item} isDayMode={d} />
          ))}
        </nav>

        <SectionLabel isDayMode={d}>Projects</SectionLabel>
        <nav className="space-y-0.5">
          {projectNav.map((item) => (
            <NavItem key={item.to} {...item} isDayMode={d} />
          ))}
        </nav>

        <SectionLabel isDayMode={d}>Resources</SectionLabel>
        <nav className="space-y-0.5">
          {resourceNav.map((item) => (
            <NavItem key={item.to} {...item} isDayMode={d} />
          ))}
        </nav>

        <SectionLabel isDayMode={d}>Integrations</SectionLabel>
        <nav className="space-y-0.5">
          {integrationNav.map((item) => (
            <NavItem key={item.to} {...item} isDayMode={d} />
          ))}
        </nav>
      </div>

      {/* Bottom cards + theme toggle */}
      <div className={`space-y-2 border-t px-3 py-3 ${d ? 'border-[#E4DED2]' : 'border-[#1e1e1e]'}`}>
        {/* Day/Night toggle */}
        <button
          type="button"
          onClick={toggleDayMode}
          className={`flex w-full items-center justify-between rounded-xl px-3.5 py-3 transition-colors ${
            d ? 'bg-[#E4DED2]/60 hover:bg-[#E4DED2]' : 'bg-[#141414] hover:bg-[#1e1e1e]'
          }`}
        >
          <div>
            <div className={`text-[13px] font-semibold ${d ? 'text-[#000]' : 'text-white'}`}>
              {d ? 'Day mode' : 'Night mode'}
            </div>
            <div className={`text-[11px] ${d ? 'text-[#9a9a9a]' : 'text-[#525252]'}`}>
              Switch to {d ? 'night' : 'day'}
            </div>
          </div>
          <div className={`flex h-8 w-8 items-center justify-center rounded-full transition-all ${
            d ? 'bg-[#F95C4B]/10 text-[#F95C4B]' : 'bg-[#F95C4B]/10 text-[#F95C4B]'
          }`}>
            {d ? <Moon size={15} /> : <Sun size={15} />}
          </div>
        </button>

        {/* Share card */}
        <div className={`flex items-center justify-between rounded-xl px-3.5 py-3 ${d ? 'bg-[#E4DED2]/60' : 'bg-[#141414]'}`}>
          <div>
            <div className={`text-[13px] font-semibold ${d ? 'text-[#000]' : 'text-white'}`}>Share BLAIQ</div>
            <div className={`text-[11px] ${d ? 'text-[#9a9a9a]' : 'text-[#525252]'}`}>Get 10 credits each</div>
          </div>
          <Gift size={16} className={d ? 'text-[#9a9a9a]' : 'text-[#525252]'} />
        </div>

        {/* Upgrade card */}
        <div className={`flex items-center justify-between rounded-xl px-3.5 py-3 ${d ? 'bg-[#E4DED2]/60' : 'bg-[#141414]'}`}>
          <div>
            <div className={`text-[13px] font-semibold ${d ? 'text-[#000]' : 'text-white'}`}>Upgrade to Pro</div>
            <div className={`text-[11px] ${d ? 'text-[#9a9a9a]' : 'text-[#525252]'}`}>Unlock more benefits</div>
          </div>
          <Sparkles size={16} className="text-[#F95C4B]" />
        </div>
      </div>
    </aside>
  );
}
