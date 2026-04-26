import React from 'react';
import { FileText, Plus, Pencil, Trash2, Shield } from 'lucide-react';

const MOCK_POLICIES = [
  { id: 1, name: 'Default Model Policy', model: 'claude-3-5-sonnet', maxTokens: 4096, temperature: 0.7, status: 'active' },
  { id: 2, name: 'Cost-Conservative', model: 'claude-3-haiku', maxTokens: 2048, temperature: 0.5, status: 'active' },
  { id: 3, name: 'Creative Sandbox', model: 'claude-3-opus', maxTokens: 8192, temperature: 1.0, status: 'draft' },
];

const STATUS_STYLES = {
  active: 'bg-emerald-500/10 text-emerald-500/70',
  draft:  'bg-amber-500/10  text-amber-500/70',
};

export default function Policy() {
  return (
    <div className="max-w-4xl mx-auto font-['Space_Grotesk']">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <Shield size={20} className="text-[#117dff]" />
          <h1 className="text-[#0a0a0a] text-2xl font-bold tracking-tight">Model &amp; Tool Policy</h1>
        </div>
        <p className="text-[#525252] text-sm ml-8">
          Define which models and tools are available per project or team.
        </p>
      </div>

      <div className="mb-4 flex items-center justify-between">
        <p className="text-[#a3a3a3] text-sm">{MOCK_POLICIES.length} policies defined</p>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#117dff] text-white rounded-lg text-sm font-semibold hover:bg-[#0066e0] transition-colors">
          <Plus size={14} /> New Policy
        </button>
      </div>

      <div className="bg-white border border-[#e3e0db] rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#e3e0db] bg-[#faf9f4]">
              <th className="text-left px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Policy Name</th>
              <th className="text-left px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Model</th>
              <th className="text-left px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Max Tokens</th>
              <th className="text-left px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Temperature</th>
              <th className="text-left px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Status</th>
              <th className="text-right px-5 py-3 text-[#a3a3a3] text-xs font-medium uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f3f1ec]">
            {MOCK_POLICIES.map((p) => (
              <tr key={p.id} className="hover:bg-[#faf9f4]/50 transition-colors">
                <td className="px-5 py-3.5">
                  <div className="flex items-center gap-2.5">
                    <FileText size={13} className="text-[#d4d0ca]" />
                    <span className="text-[#0a0a0a] font-medium">{p.name}</span>
                  </div>
                </td>
                <td className="px-5 py-3.5 text-[#525252] font-mono text-xs">{p.model}</td>
                <td className="px-5 py-3.5 text-[#525252] font-mono text-xs">{p.maxTokens.toLocaleString()}</td>
                <td className="px-5 py-3.5 text-[#525252] font-mono text-xs">{p.temperature}</td>
                <td className="px-5 py-3.5">
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded uppercase ${STATUS_STYLES[p.status]}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-5 py-3.5">
                  <div className="flex items-center justify-end gap-1">
                    <button className="p-1.5 rounded-md hover:bg-[#f3f1ec] text-[#a3a3a3] hover:text-[#525252] transition-colors">
                      <Pencil size={12} />
                    </button>
                    <button className="p-1.5 rounded-md hover:bg-[#dc2626]/5 text-[#a3a3a3] hover:text-[#dc2626] transition-colors">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}