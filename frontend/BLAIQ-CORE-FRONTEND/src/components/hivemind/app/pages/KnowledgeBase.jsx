import React from 'react';
import { Database, FileStack } from 'lucide-react';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';

export default function KnowledgeBase() {
  const { evidenceSummary, routingDecision, timeline } = useBlaiqWorkspace();

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_360px] gap-6 overflow-hidden p-6">
      <section className="min-h-0 overflow-y-auto border border-[#ddd6c8] bg-white p-5">
        <div className="mb-5 flex items-center gap-2">
          <Database size={16} className="text-[#117dff]" />
          <div className="font-['Space_Grotesk'] text-lg font-semibold">Workflow context</div>
        </div>
        <div className="space-y-4">
          <div className="border border-[#e5dfd3] bg-[#faf7f1] p-4">
            <div className="text-[11px] font-mono uppercase tracking-[0.12em] text-[#6b7280]">Routing context</div>
            <div className="mt-2 text-sm text-[#111827]">{routingDecision?.reasoning || 'Routing context will appear after the strategist runs.'}</div>
          </div>
          <div className="border border-[#e5dfd3] bg-[#faf7f1] p-4">
            <div className="text-[11px] font-mono uppercase tracking-[0.12em] text-[#6b7280]">Evidence summary</div>
            <div className="mt-2 text-sm text-[#111827]">{evidenceSummary?.message || evidenceSummary?.summary || 'GraphRAG evidence summary will appear here.'}</div>
          </div>
        </div>
      </section>
      <aside className="border border-[#ddd6c8] bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <FileStack size={16} className="text-[#117dff]" />
          <div className="font-['Space_Grotesk'] text-lg font-semibold">Run ledger</div>
        </div>
        <div className="space-y-2">
          {timeline.length === 0 ? <div className="text-sm text-[#6b7280]">No run history yet.</div> : timeline.map((item) => (
            <div key={`${item.label}-${item.at}`} className="border border-[#e5dfd3] bg-[#faf7f1] px-3 py-2">
              <div className="text-sm font-medium text-[#111827]">{item.label}</div>
              <div className="mt-1 text-[11px] font-mono text-[#6b7280]">{item.state} · {item.at}</div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
