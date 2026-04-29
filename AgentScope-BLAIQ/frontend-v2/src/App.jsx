import React, { useState } from 'react';
import { useAgentStore } from './store/useAgentStore';
import { telemetry } from './api/sse-client';
import { 
  Send, 
  Terminal, 
  Activity, 
  Zap, 
  Layers, 
  Maximize2 
} from 'lucide-react';

export default function App() {
  const [input, setInput] = useState('');
  const { agents, messages } = useAgentStore();

  const handleSend = () => {
    if (!input.trim()) return;
    telemetry.sendCommand(input);
    setInput('');
  };

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0a] text-white overflow-hidden font-sans">
      {/* LEFT: SWARM PULSE (Agent Activity) */}
      <aside className="w-80 border-r border-white/5 bg-white/[0.02] flex flex-col">
        <div className="p-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-yellow-500" />
            <span className="text-xs font-bold uppercase tracking-widest opacity-60">Swarm Pulse</span>
          </div>
          <Layers className="w-4 h-4 opacity-30" />
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {Object.entries(agents).map(([name, data]) => (
            <div key={name} className="glass-card rounded-lg p-3 space-y-2 border border-white/10">
              <div className="flex justify-between items-center">
                <span className="text-sm font-medium text-yellow-200/80">{name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-tighter ${
                  data.status === 'active' ? 'bg-blue-500/20 text-blue-400' : 'bg-white/5 text-white/40'
                }`}>
                  {data.status}
                </span>
              </div>
              <div className="text-[11px] font-mono opacity-40 h-20 overflow-hidden line-clamp-4">
                {data.thoughts || "Waiting for signal..."}
              </div>
            </div>
          ))}
          {Object.keys(agents).length === 0 && (
            <div className="text-center py-20 opacity-20 text-xs italic">
              No active swarm signals...
            </div>
          )}
        </div>
      </aside>

      {/* CENTER: DELIVERY STAGE */}
      <main className="flex-1 flex flex-col relative bg-gradient-to-b from-transparent to-white/[0.01]">
        <header className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-black/20 backdrop-blur-xl z-10">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
            <h1 className="text-sm font-semibold tracking-tight text-white/90">BLAIQ <span className="text-yellow-500/80">V2</span></h1>
          </div>
          <div className="flex gap-4 opacity-40">
             <Maximize2 className="w-4 h-4" />
          </div>
        </header>

        <section className="flex-1 overflow-y-auto p-8 max-w-4xl mx-auto w-full space-y-8">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] p-4 rounded-2xl ${
                m.role === 'user' 
                  ? 'bg-yellow-500/10 border border-yellow-500/20 text-yellow-50' 
                  : 'bg-white/[0.03] border border-white/10 text-white/90'
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full opacity-10 space-y-4">
              <Zap className="w-12 h-12" />
              <p className="text-sm tracking-widest uppercase">Awaiting Command</p>
            </div>
          )}
        </section>

        {/* FLOATING COMMAND BAR */}
        <div className="p-6">
          <div className="max-w-3xl mx-auto relative group">
            <div className="absolute -inset-0.5 bg-gradient-to-r from-yellow-500/20 to-blue-500/20 rounded-2xl blur opacity-30 group-hover:opacity-100 transition duration-1000"></div>
            <div className="relative flex items-center bg-[#111] border border-white/10 rounded-2xl overflow-hidden shadow-2xl">
              <input 
                type="text" 
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Direct swarm command..."
                className="flex-1 bg-transparent px-6 py-4 text-sm focus:outline-none placeholder:text-white/20"
              />
              <button 
                onClick={handleSend}
                className="p-4 text-yellow-500 hover:text-yellow-400 transition-colors"
                disabled={!input.trim()}
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* RIGHT: ARTIFACTS / CONTEXT (Hidden for MVP) */}
      <div className="w-12 border-l border-white/5 bg-black/40 flex flex-col items-center py-4 gap-6 opacity-30 hover:opacity-100 transition-opacity">
        <Terminal className="w-5 h-5" />
        <Activity className="w-5 h-5" />
      </div>
    </div>
  );
}
