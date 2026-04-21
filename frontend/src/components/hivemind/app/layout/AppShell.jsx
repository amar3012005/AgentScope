import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';

export default function AppShell() {
  const { isDayMode } = useBlaiqWorkspace();

  return (
    <div className={`bmw-shell ${isDayMode ? 'bmw-shell-day' : 'bmw-shell-night'}`}>
      <div className="bmw-sidebar-wrap">
        <Sidebar />
      </div>

      <main className="bmw-main">
        <TopBar />
        <Outlet />
      </main>
    </div>
  );
}
