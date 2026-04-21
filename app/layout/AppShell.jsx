import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { useAuth } from '../auth/AuthProvider';
import OnboardingFlow from '../pages/Onboarding';
import { ChatPanel } from '../pages/Chat';
import { Brain } from 'lucide-react';

/**
 * AppShell — layout:
 *   1. needs_org_setup -> show org creation
 *   2. otherwise -> full dashboard (API key generated on-demand when needed)
 */
export default function AppShell() {
  const { needsOnboarding } = useAuth();
  const [chatOpen, setChatOpen] = useState(false);

  if (needsOnboarding) {
    return <OnboardingFlow />;
  }

  return (
    <div className="min-h-screen bg-[#faf9f4] font-[Inter,ui-sans-serif,system-ui,sans-serif]">
      <Sidebar />
      <div className="ml-[260px] flex flex-col min-h-screen transition-all duration-200">
        <TopBar />
        <main className="flex-1 p-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      {/* Chat FAB */}
      <button
        onClick={() => setChatOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-5 py-3 bg-[#117dff] text-white rounded-full shadow-[0_4px_24px_rgba(17,125,255,0.3)] hover:bg-[#0066e0] transition-all group"
      >
        <Brain size={18} />
        <span className="text-sm font-semibold font-['Space_Grotesk']">Talk to HIVE</span>
      </button>

      {/* Chat Panel */}
      <ChatPanel isOpen={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
