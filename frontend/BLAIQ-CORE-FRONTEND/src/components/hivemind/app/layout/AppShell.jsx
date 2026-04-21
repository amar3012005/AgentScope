import React, { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';

export default function AppShell() {
  const { hasConversation, isDayMode } = useBlaiqWorkspace();

  const [showSidebar, setShowSidebar] = useState(false);

  useEffect(() => {
    if (hasConversation && !showSidebar) {
      const raf1 = requestAnimationFrame(() => {
        const raf2 = requestAnimationFrame(() => setShowSidebar(true));
        return () => cancelAnimationFrame(raf2);
      });
      return () => cancelAnimationFrame(raf1);
    }
    if (!hasConversation) setShowSidebar(false);
  }, [hasConversation, showSidebar]);

  return (
    <div
      className={`hero-gradient flex h-screen w-screen overflow-hidden font-[Inter,ui-sans-serif,system-ui,sans-serif] ${
        isDayMode ? 'day' : ''
      }`}
    >
      {/* Sidebar — slides in from left */}
      <div
        className="flex-shrink-0 max-lg:hidden"
        style={{
          width: showSidebar ? 240 : 0,
          opacity: showSidebar ? 1 : 0,
          transform: showSidebar ? 'translateX(0)' : 'translateX(-60px)',
          overflow: 'hidden',
          transition: 'width 1s cubic-bezier(0.16,1,0.3,1), opacity 1s cubic-bezier(0.16,1,0.3,1), transform 1s cubic-bezier(0.16,1,0.3,1)',
          transitionDelay: '0.15s',
        }}
      >
        <Sidebar />
      </div>
      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
