import { create } from 'zustand';

export const useAgentStore = create((set, get) => ({
  // Core State
  agents: {}, // { "Strategist": { status: "thinking", logs: [], thoughts: "" } }
  messages: [],
  isStreaming: false,
  currentWorkflow: null,

  // Actions
  addEvent: (event) => {
    const { type, agent_name, content, metadata } = event;
    
    set((state) => {
      const newAgents = { ...state.agents };
      const agentKey = agent_name || 'System';
      
      if (!newAgents[agentKey]) {
        newAgents[agentKey] = { status: 'idle', logs: [], thoughts: '', lastUpdate: Date.now() };
      }

      const agent = newAgents[agentKey];

      switch (type) {
        case 'agent_started':
          agent.status = 'active';
          agent.logs.push({ t: Date.now(), msg: `Started: ${metadata?.phase || 'Processing'}` });
          break;
        
        case 'agent_thought':
          agent.thoughts = (agent.thoughts || '') + content;
          agent.status = 'thinking';
          break;
        
        case 'token_chunk':
          // Token chunks for the main delivery stage
          return { 
            messages: state.messages.length > 0 
              ? [...state.messages.slice(0, -1), { ...state.messages[state.messages.length-1], content: state.messages[state.messages.length-1].content + content }]
              : [{ role: 'assistant', content }]
          };

        case 'agent_completed':
          agent.status = 'completed';
          agent.logs.push({ t: Date.now(), msg: 'Task completed' });
          break;

        default:
          if (content) {
            agent.logs.push({ t: Date.now(), msg: content });
          }
      }

      return { agents: newAgents };
    });
  },

  reset: () => set({ agents: {}, messages: [], isStreaming: false })
}));
