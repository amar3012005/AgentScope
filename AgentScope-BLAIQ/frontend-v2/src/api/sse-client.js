import { useAgentStore } from '../store/useAgentStore';

class SwarmTelemetry {
  constructor() {
    this.controller = null;
    this.baseUrl = 'http://localhost:8090/api'; // Standard Orchestrator Port
  }

  async sendCommand(query, workflowMode = 'hybrid') {
    const store = useAgentStore.getState();
    store.reset();
    
    // 1. Initial UI feedback
    store.addEvent({ 
      role: 'user', 
      content: query 
    });

    try {
      // 2. Start SSE Stream
      const response = await fetch(`${this.baseUrl}/workflow/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          workflow_mode: workflowMode,
          session_id: `v2-${Date.now()}`
        })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          
          try {
            const data = JSON.parse(line.slice(6));
            // Direct injection into Zustand (No React Context Overhead)
            store.addEvent(data);
          } catch (e) {
            console.warn("Failed to parse event:", line);
          }
        }
      }
    } catch (error) {
      console.error("Swarm Stream Error:", error);
      store.addEvent({ 
        type: 'error', 
        content: "Lost connection to Swarm Engine." 
      });
    }
  }

  abort() {
    if (this.controller) this.controller.abort();
  }
}

export const telemetry = new SwarmTelemetry();
