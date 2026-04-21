import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/hivemind/app/layout/AppShell';
import Overview from './components/hivemind/app/pages/Overview';
import Chat from './components/hivemind/app/pages/Chat';
import AgentSwarm from './components/hivemind/app/pages/AgentSwarm';
import KnowledgeBase from './components/hivemind/app/pages/KnowledgeBase';
import Settings from './components/hivemind/app/pages/Settings';
import Preview from './components/hivemind/app/pages/Preview';
import Hivemind from './components/hivemind/app/pages/Hivemind';
import { BlaiqWorkspaceProvider } from './components/hivemind/app/shared/blaiq-workspace-context';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          height: '100vh', background: '#0a0a0a', color: '#F6F4F1', fontFamily: 'monospace', padding: '2rem', textAlign: 'center',
        }}>
          <div style={{ color: '#F95C4B', fontSize: '18px', fontWeight: 'bold', marginBottom: '12px' }}>
            Runtime error
          </div>
          <pre style={{ color: '#a1a1a1', fontSize: '13px', maxWidth: '80vw', overflowX: 'auto', background: '#111', padding: '16px', borderRadius: '8px', textAlign: 'left' }}>
            {this.state.error?.message}
            {'\n'}
            {this.state.error?.stack?.split('\n').slice(1, 6).join('\n')}
          </pre>
          <button
            style={{ marginTop: '20px', padding: '8px 20px', background: '#F95C4B', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer' }}
            onClick={() => { window.localStorage.clear(); window.location.reload(); }}
          >
            Clear cache &amp; reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <BlaiqWorkspaceProvider>
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<Navigate to="/app/chat" replace />} />
              <Route path="app">
                <Route index element={<Navigate to="/app/chat" replace />} />
                <Route path="overview" element={<Overview />} />
                <Route path="chat" element={<Chat />} />
                <Route path="agents" element={<AgentSwarm />} />
                <Route path="preview" element={<Preview />} />
                <Route path="knowledge" element={<KnowledgeBase />} />
                <Route path="settings" element={<Settings />} />
                <Route path="hivemind" element={<Hivemind />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/app/chat" replace />} />
          </Routes>
        </BlaiqWorkspaceProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
