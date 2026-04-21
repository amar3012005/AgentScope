import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/hivemind/app/layout/AppShell';
import Chat from './components/hivemind/app/pages/Chat';
import KnowledgeBase from './components/hivemind/app/pages/KnowledgeBase';
import BrandDna from './components/hivemind/app/pages/BrandDna';
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
          height: '100vh', background: '#ffffff', color: '#262626', fontFamily: 'Rajdhani, Helvetica, Arial, sans-serif', padding: '2rem', textAlign: 'center',
        }}>
          <div style={{ color: '#b91c1c', fontSize: '20px', fontWeight: 700, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Something went wrong
          </div>
          <pre style={{ color: '#757575', fontSize: '13px', maxWidth: '80vw', overflowX: 'auto', background: '#f4f4f4', padding: '16px', border: '1px solid #d4d4d4', borderRadius: 0, textAlign: 'left' }}>
            {this.state.error?.message}
            {'\n'}
            {this.state.error?.stack?.split('\n').slice(1, 6).join('\n')}
          </pre>
          <button
            style={{ marginTop: '20px', padding: '10px 20px', background: '#262626', border: '1px solid #262626', borderRadius: 0, color: '#ffffff', cursor: 'pointer', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}
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
                <Route path="chat" element={<Chat />} />
                <Route path="chat/:sessionId" element={<Chat />} />
                <Route path="hivemind" element={<KnowledgeBase />} />
                <Route path="brand-dna" element={<BrandDna />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/app/chat" replace />} />
          </Routes>
        </BlaiqWorkspaceProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
