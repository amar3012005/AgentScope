import React from 'react';
import {
  BookOpen,
  Bot,
  CheckCircle2,
  CircleDashed,
  Database,
  Folder,
  Palette,
  Loader2,
  Moon,
  Plus,
  Search,
  Sparkles,
  Sun,
  XCircle,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';

function TaskStatusIcon({ status }) {
  if (status === 'complete') return <CheckCircle2 size={14} className="text-[#1c69d4]" />;
  if (status === 'running') return <Loader2 size={14} className="animate-spin text-[#1c69d4]" />;
  if (status === 'error') return <XCircle size={14} className="text-[#b91c1c]" />;
  return <CircleDashed size={14} className="text-[#757575]" />;
}

function NavButton({ icon: Icon, label, active, onClick, muted = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`bmw-nav-btn ${active ? 'bmw-nav-btn-active' : ''} ${muted ? 'bmw-nav-btn-muted' : ''}`}
      aria-current={active ? 'page' : undefined}
    >
      <Icon size={18} strokeWidth={2} />
      <span className="bmw-nav-label">{label}</span>
    </button>
  );
}

function SessionButton({ selected, children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`bmw-session-btn ${selected ? 'bmw-session-btn-active' : ''}`}
    >
      {children}
    </button>
  );
}

function truncateLabel(text, max = 33) {
  if (!text) return 'Untitled task';
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

export default function Sidebar() {
  const {
    tasks,
    activeTaskId,
    resetWorkspace,
    isDayMode,
    toggleDayMode,
    sessions,
    sessionId,
    switchSession,
    createNewSession,
  } = useBlaiqWorkspace();
  const navigate = useNavigate();
  const location = useLocation();

  const activePath = location.pathname;
  const activeTask = tasks.find((task) => task.id === activeTaskId) || null;

  const openChat = (targetSessionId = sessionId) => navigate(targetSessionId ? `/app/chat/${targetSessionId}` : '/app/chat');
  const openHivemind = () => navigate('/app/hivemind');
  const openBrandDna = () => navigate('/app/brand-dna');

  const handleNewChat = () => {
    const newSessionId = createNewSession();
    resetWorkspace();
    openChat(newSessionId);
  };

  const handleSwitchSession = (newSessionId) => {
    switchSession(newSessionId);
    openChat(newSessionId);
  };

  return (
    <aside className={`bmw-sidebar ${isDayMode ? 'bmw-sidebar-day' : 'bmw-sidebar-night'}`}>
      <div className="bmw-sidebar-header">
        <button type="button" onClick={openChat} className="flex items-center gap-3 text-left">
          <div className="bmw-mark">
            <Sparkles size={18} strokeWidth={2} />
          </div>
          <div>
            <div className="bmw-brand-title">BLAIQ</div>
            <div className="bmw-meta">Agent Workspace</div>
          </div>
        </button>
      </div>

      <div className="bmw-nav-section">
        <NavButton
          icon={Plus}
          label="New Task"
          active={activePath.startsWith('/app/chat')}
          onClick={handleNewChat}
        />
        <div className="h-1" />
        <NavButton icon={Bot} label="Agents" onClick={openChat} muted />
        <NavButton icon={Search} label="Search" onClick={openChat} muted />
        <NavButton icon={BookOpen} label="Library" onClick={openChat} muted />
        <NavButton
          icon={Database}
          label="HIVEMIND"
          active={activePath.startsWith('/app/hivemind')}
          onClick={openHivemind}
        />
        <NavButton
          icon={Palette}
          label="Brand DNA"
          active={activePath.startsWith('/app/brand-dna')}
          onClick={openBrandDna}
        />
      </div>

      <div className="bmw-block">
        <div className="flex items-center justify-between">
          <div className="bmw-section-label">Sessions</div>
          <button
            type="button"
            onClick={handleNewChat}
            className="bmw-mini-btn"
            title="New session"
          >
            +
          </button>
        </div>
        <button
          type="button"
          onClick={handleNewChat}
          className="bmw-nav-btn mt-3"
        >
          <Folder size={18} strokeWidth={2} />
          <div>
            <div className="bmw-nav-label">BLAIQ</div>
            <div className="bmw-meta">Active Workspace</div>
          </div>
        </button>
      </div>

      <div className="min-h-0 flex-1 px-4 pb-4 pt-6">
        <div className="flex items-center justify-between px-1">
          <div className="bmw-section-label">Recent Sessions</div>
          <button
            type="button"
            onClick={handleNewChat}
            className="bmw-mini-btn"
            title="New session"
          >
            +
          </button>
        </div>

        <div className="mt-3 space-y-1.5 overflow-y-auto pr-1">
          {sessions.length === 0 ? (
            <div className="bmw-empty-state">
              No sessions yet. Start a new chat to create one.
            </div>
          ) : (
            sessions.map((session) => {
              const selected = session.id === sessionId;
              const date = new Date(session.lastUsedAt || session.createdAt);
              const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
              return (
                <SessionButton
                  key={session.id}
                  onClick={() => handleSwitchSession(session.id)}
                  selected={selected}
                >
                  <div className="pt-0.5">
                    <BookOpen size={14} className={selected ? 'text-[#1c69d4]' : 'text-[#757575]'} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-bold uppercase leading-[1.2] tracking-[0.08em]">
                      {session.title || 'Untitled Session'}
                    </div>
                    <div className="mt-1 text-[11px] uppercase tracking-[0.08em] text-[#757575]">
                      {dateStr} · {session.id.slice(0, 8)}
                    </div>
                  </div>
                  <TaskStatusIcon status={selected ? 'running' : 'pending'} />
                </SessionButton>
              );
            })
          )}
        </div>
      </div>

      <div className="bmw-footer">
        <button
          type="button"
          onClick={toggleDayMode}
          className="bmw-mode-toggle"
        >
          <div>
            <div className="bmw-nav-label">{isDayMode ? 'Day Mode' : 'Night Mode'}</div>
            <div className="bmw-meta">Switch Workspace Theme</div>
          </div>
          {isDayMode ? <Moon size={16} strokeWidth={2} /> : <Sun size={16} strokeWidth={2} />}
        </button>
        <div className="mt-3 text-center text-[11px] uppercase tracking-[0.08em] text-[#757575]">
          {activeTask ? `Focused on: ${truncateLabel(activeTask.query, 24)}` : 'No active task selected'}
        </div>
      </div>
    </aside>
  );
}
