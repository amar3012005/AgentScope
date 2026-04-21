import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useHealthStatus } from '../shared/hooks';
import { Search, BookOpen } from 'lucide-react';

const pageTitles = {
  '/hivemind/app/overview': 'Overview',
  '/hivemind/app/memories': 'Memories',
  '/hivemind/app/keys': 'API Keys',
  '/hivemind/app/connectors': 'Connectors',
  '/hivemind/app/profile': 'Profile',
  '/hivemind/app/evaluation': 'Evaluation',
  '/hivemind/app/settings': 'Settings',
  '/hivemind/app/billing': 'Billing',
  '/hivemind/app/web': 'Web Intelligence',
  '/hivemind/app/web-admin': 'Web Admin',
  '/hivemind/app/mcp': 'MCP Server',
  '/hivemind/app/graph': 'Memory Graph',
  '/hivemind/app/engine': 'Engine Intelligence',
};

const pageDescriptions = {
  '/hivemind/app/overview': 'Your memory engine at a glance',
  '/hivemind/app/memories': 'Browse and manage stored knowledge',
  '/hivemind/app/keys': 'Manage API authentication keys',
  '/hivemind/app/connectors': 'Connect data sources and AI clients',
  '/hivemind/app/profile': 'Your memory footprint and context',
  '/hivemind/app/evaluation': 'Test retrieval quality',
  '/hivemind/app/settings': 'Workspace configuration',
  '/hivemind/app/billing': 'Manage your plan and usage',
  '/hivemind/app/web': 'Search and crawl the web as async jobs',
  '/hivemind/app/web-admin': 'Operational metrics, success rates, and runtime health',
  '/hivemind/app/mcp': '13 MCP tools for memory, search, and web intelligence — with setup guides',
  '/hivemind/app/graph': 'Explore connections between memories — semantic clusters, temporal decay, and relationship traversal',
  '/hivemind/app/engine': 'SOTA memory engine — cognitive framing, temporal queries, swarm reasoning, and Byzantine consensus',
};

export default function TopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const healthy = useHealthStatus();

  const title = pageTitles[location.pathname] || 'HIVEMIND';
  const description = pageDescriptions[location.pathname] || '';

  return (
    <header className="h-14 bg-[#faf9f4]/90 backdrop-blur-xl border-b border-[#e3e0db] flex items-center justify-between px-6 sticky top-0 z-30">
      {/* Left: Title + Description */}
      <div className="flex items-center gap-3 min-w-0">
        <div>
          <h1 className="text-[#0a0a0a] text-[15px] font-semibold font-['Space_Grotesk'] tracking-tight leading-none">
            {title}
          </h1>
          {description && (
            <p className="text-[#a3a3a3] text-[11px] mt-0.5">
              {description}
            </p>
          )}
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {/* Global Search */}
        <button
          onClick={() => navigate('/hivemind/app/memories')}
          className="flex items-center gap-2 h-8 px-3 rounded-[6px] bg-[#f3f1ec] border border-[#e3e0db] hover:border-[#d4d0ca] text-[#a3a3a3] hover:text-[#525252] transition-all text-xs"
        >
          <Search size={13} />
          <span className="hidden md:inline">Search memories...</span>
          <kbd className="hidden md:inline text-[10px] font-mono text-[#a3a3a3] bg-[#eae7e1] rounded px-1 py-0.5 ml-4">
            /
          </kbd>
        </button>

        {/* Docs */}
        <a
          href="https://docs.hivemind.dev"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center w-8 h-8 rounded-[6px] hover:bg-[#f3f1ec] text-[#a3a3a3] hover:text-[#525252] transition-colors"
          title="Documentation"
        >
          <BookOpen size={15} />
        </a>

        {/* Health */}
        <div className="flex items-center gap-1.5 h-8 px-2.5 rounded-[6px] bg-[#f3f1ec] border border-[#e3e0db]">
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              healthy === null
                ? 'bg-[#a3a3a3]'
                : healthy
                ? 'bg-[#16a34a]'
                : 'bg-[#dc2626]'
            }`}
          />
          <span className="text-[10px] text-[#a3a3a3] font-mono whitespace-nowrap">
            {healthy === null ? '...' : healthy ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>
    </header>
  );
}
