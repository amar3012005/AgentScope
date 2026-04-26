import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  LayoutDashboard,
  Brain,
  Key,
  Cable,
  User,
  FlaskConical,
  Settings,
  LogOut,
  Hexagon,
  CreditCard,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Globe,
  ShieldCheck,
  Server,
  Network,
  Cpu,
  BookOpen,
  Bot,
  CheckCircle,
} from 'lucide-react';
import { useAuth } from '../auth/AuthProvider';
import apiClient from '../shared/api-client';

/** Build nav sections, conditionally including admin items. */
function buildNavSections({ showWebAdmin }) {
  const devItems = [
    { to: '/hivemind/app/keys', icon: Key, label: 'API Keys' },
    { to: '/hivemind/app/mcp', icon: Server, label: 'MCP Server' },
    { to: '/hivemind/app/evaluation', icon: FlaskConical, label: 'Evaluation' },
  ];
  if (showWebAdmin) {
    devItems.push({ to: '/hivemind/app/web-admin', icon: ShieldCheck, label: 'Web Admin' });
  }
  return [
    {
      label: null,
      items: [
        { to: '/hivemind/app/overview', icon: LayoutDashboard, label: 'Overview' },
      ],
    },
    {
      label: 'Data',
      items: [
        { to: '/hivemind/app/memories', icon: Brain, label: 'Memories' },
        { to: '/hivemind/app/graph', icon: Network, label: 'Memory Graph' },
        { to: '/hivemind/app/engine', icon: Cpu, label: 'Engine' },
        { to: '/hivemind/app/knowledge', icon: BookOpen, label: 'Knowledge Base' },
        { to: '/hivemind/app/connectors', icon: Cable, label: 'Connectors' },
        { to: '/hivemind/app/web', icon: Globe, label: 'Web Intel' },
        { to: '/hivemind/app/swarm', icon: Bot, label: 'Agent Swarm' },
        { to: '/hivemind/app/profile', icon: User, label: 'Profile' },
      ],
    },
    {
      label: 'Governance',
      items: [
        { to: '/hivemind/app/policy', icon: ShieldCheck, label: 'Policy' },
        { to: '/hivemind/app/approval-workflow', icon: CheckCircle, label: 'Approval' },
      ],
    },
    {
      label: 'Developer',
      items: devItems,
    },
    {
      label: 'Account',
      items: [
        { to: '/hivemind/app/billing', icon: CreditCard, label: 'Billing' },
        { to: '/hivemind/app/settings', icon: Settings, label: 'Settings' },
      ],
    },
  ];
}

export default function Sidebar() {
  const { logout, org, user } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [showWebAdmin, setShowWebAdmin] = useState(false);

  // Probe admin access once on mount
  useEffect(() => {
    apiClient.getWebAdminMetrics()
      .then(() => setShowWebAdmin(true))
      .catch(() => setShowWebAdmin(false));
  }, []);

  const navSections = buildNavSections({ showWebAdmin });

  const sidebarWidth = collapsed ? 'w-[68px]' : 'w-[260px]';

  return (
    <aside
      className={`fixed left-0 top-0 bottom-0 ${sidebarWidth} bg-[#faf9f4] border-r border-[#e3e0db] flex flex-col z-40 transition-all duration-200`}
    >
      {/* Logo */}
      <div className="h-14 flex items-center justify-between px-4 border-b border-[#e3e0db]">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-[#117dff]/10 flex items-center justify-center flex-shrink-0">
            <Hexagon size={16} className="text-[#117dff]" />
          </div>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: 'auto' }}
              exit={{ opacity: 0, width: 0 }}
              className="flex flex-col overflow-hidden"
            >
              <span className="text-[#0a0a0a] text-[13px] font-semibold tracking-wide font-['Space_Grotesk'] whitespace-nowrap">
                HIVEMIND
              </span>
              {org && (
                <span className="text-[#a3a3a3] text-[10px] font-mono truncate max-w-[140px]">
                  {org.name || org.slug || org.id?.slice(0, 8)}
                </span>
              )}
            </motion.div>
          )}
        </div>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 rounded-md hover:bg-[#f3f1ec] text-[#a3a3a3] hover:text-[#525252] transition-colors flex-shrink-0"
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2.5 overflow-y-auto space-y-4">
        {navSections.map((section, si) => (
          <div key={si}>
            {section.label && !collapsed && (
              <div className="px-2.5 mb-1.5">
                <span className="text-[#a3a3a3] text-[10px] font-medium uppercase tracking-[0.08em]">
                  {section.label}
                </span>
              </div>
            )}
            {collapsed && section.label && (
              <div className="h-px bg-[#e3e0db] mx-2 mb-2" />
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const isActive =
                  location.pathname === item.to ||
                  (item.to !== '/hivemind/app/overview' && location.pathname.startsWith(item.to));

                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={`relative flex items-center ${collapsed ? 'justify-center' : ''} gap-2.5 px-2.5 py-2 rounded-lg text-[13px] transition-all duration-150 group`}
                    title={collapsed ? item.label : undefined}
                  >
                    {isActive && (
                      <motion.div
                        layoutId="sidebar-active"
                        className="absolute inset-0 bg-[#f3f1ec] rounded-lg"
                        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                      />
                    )}
                    <item.icon
                      size={18}
                      strokeWidth={1.75}
                      className={`relative z-10 transition-colors flex-shrink-0 ${
                        isActive ? 'text-[#0a0a0a]' : 'text-[#a3a3a3] group-hover:text-[#525252]'
                      }`}
                    />
                    {!collapsed && (
                      <span
                        className={`relative z-10 transition-colors truncate ${
                          isActive ? 'text-[#0a0a0a] font-medium' : 'text-[#525252] group-hover:text-[#0a0a0a]'
                        }`}
                      >
                        {item.label}
                      </span>
                    )}
                    {!collapsed && item.label === 'Billing' && (
                      <span className="relative z-10 ml-auto text-[9px] font-mono bg-[#117dff]/10 text-[#117dff] px-1.5 py-0.5 rounded">
                        PRO
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Upgrade Banner */}
      {!collapsed && (
        <div className="mx-2.5 mb-2">
          <div className="bg-[#117dff]/[0.04] border border-[#117dff]/10 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-1.5">
              <Sparkles size={14} className="text-[#117dff]" />
              <span className="text-[#0a0a0a] text-xs font-semibold">
                Upgrade to Pro
              </span>
            </div>
            <p className="text-[#a3a3a3] text-[10px] leading-relaxed mb-2.5">
              Unlock unlimited memories, priority support, and advanced connectors.
            </p>
            <NavLink
              to="/hivemind/app/billing"
              className="block text-center text-[11px] font-semibold uppercase tracking-[0.075em] bg-[#117dff] text-white rounded-[4px] py-1.5 hover:bg-[#0066e0] transition-colors"
            >
              View Plans
            </NavLink>
          </div>
        </div>
      )}

      {/* User + Logout */}
      <div className="p-2.5 border-t border-[#e3e0db]">
        {!collapsed && user && (
          <div className="flex items-center gap-2.5 px-2 py-1.5 mb-1">
            <div className="w-7 h-7 rounded-full bg-[#117dff]/10 flex items-center justify-center flex-shrink-0">
              <span className="text-[#117dff] text-[10px] font-bold font-mono">
                {(user.display_name || user.email || 'U')[0].toUpperCase()}
              </span>
            </div>
            <div className="min-w-0">
              <p className="text-[#0a0a0a] text-xs truncate">
                {user.display_name || user.email || 'User'}
              </p>
              <p className="text-[#a3a3a3] text-[10px] font-mono truncate">
                Free Plan
              </p>
            </div>
          </div>
        )}
        <button
          onClick={logout}
          className={`flex items-center ${collapsed ? 'justify-center' : ''} gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] text-[#a3a3a3] hover:text-[#dc2626] hover:bg-[#dc2626]/5 transition-all`}
          title={collapsed ? 'Sign Out' : undefined}
        >
          <LogOut size={16} />
          {!collapsed && <span>Sign Out</span>}
        </button>
      </div>
    </aside>
  );
}
