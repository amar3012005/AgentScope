import React, { useState } from 'react';
import { CheckCircle, XCircle, Clock, User, MessageSquare, ChevronDown, ChevronUp } from 'lucide-react';

const MOCK_REQUESTS = [
  { id: 1, user: 'alice@example.com', action: 'Run claude-3-opus on customer data', status: 'pending', timestamp: '2026-04-23T10:30:00Z' },
  { id: 2, user: 'bob@example.com',  action: 'Bulk export 5,000 memories',          status: 'pending', timestamp: '2026-04-23T09:15:00Z' },
  { id: 3, user: 'carol@example.com', action: 'Enable webhook on billing project',  status: 'approved', timestamp: '2026-04-22T16:00:00Z' },
  { id: 4, user: 'dave@example.com', action: 'Delete knowledge base "Q4 Strategy"', status: 'rejected', timestamp: '2026-04-22T14:30:00Z' },
];

const STATUS_STYLES = {
  pending:  'text-amber-500/70',
  approved: 'text-emerald-500/70',
  rejected: 'text-red-500/70',
};
const STATUS_BG = {
  pending:  'bg-amber-500/10',
  approved: 'bg-emerald-500/10',
  rejected: 'bg-red-500/10',
};

export default function ApprovalWorkflow() {
  const [expanded, setExpanded] = useState(null);
  const [localStatus, setLocalStatus] = useState(
    Object.fromEntries(MOCK_REQUESTS.map((r) => [r.id, r.status]))
  );

  function handleAction(id, action) {
    setLocalStatus((prev) => ({ ...prev, [id]: action }));
  }

  const pending = MOCK_REQUESTS.filter((r) => r.status === 'pending' || localStatus[r.id] === 'pending');

  return (
    <div className="max-w-4xl mx-auto font-['Space_Grotesk']">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <CheckCircle size={20} className="text-[#117dff]" />
          <h1 className="text-[#0a0a0a] text-2xl font-bold tracking-tight">Approval Workflow</h1>
        </div>
        <p className="text-[#525252] text-sm ml-8">
          Review and approve or reject runs that require manager sign-off.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: 'Pending',  color: 'text-amber-500',  bg: 'bg-amber-500/10'  },
          { label: 'Approved', color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
          { label: 'Rejected', color: 'text-red-500',   bg: 'bg-red-500/10'   },
        ].map(({ label, color, bg }) => {
          const count = MOCK_REQUESTS.filter((r) => {
            const s = localStatus[r.id] ?? r.status;
            return label.toLowerCase() === s;
          }).length;
          return (
            <div key={label} className="bg-white border border-[#e3e0db] rounded-xl p-4 flex items-center gap-3">
              <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${bg}`}>
                {label === 'Pending' ? <Clock size={16} className={color} />
                  : label === 'Approved' ? <CheckCircle size={16} className={color} />
                  : <XCircle size={16} className={color} />}
              </div>
              <div>
                <p className="text-[#a3a3a3] text-xs uppercase tracking-wider">{label}</p>
                <p className={`text-xl font-mono font-semibold ${color}`}>{count}</p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="space-y-3">
        {MOCK_REQUESTS.map((req) => {
          const s = localStatus[req.id] ?? req.status;
          const isExpanded = expanded === req.id;
          const isPending = s === 'pending';

          return (
            <div key={req.id} className="bg-white border border-[#e3e0db] rounded-xl overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <button
                onClick={() => setExpanded(isExpanded ? null : req.id)}
                className="w-full flex items-center gap-3 px-5 py-4 hover:bg-[#faf9f4]/50 transition-colors text-left"
              >
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${STATUS_BG[s]}`}>
                  {s === 'pending'  ? <Clock size={14}       className={STATUS_STYLES[s]} />
                   : s === 'approved' ? <CheckCircle size={14} className={STATUS_STYLES[s]} />
                   : <XCircle size={14}                    className={STATUS_STYLES[s]} />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[#0a0a0a] text-sm font-medium truncate">{req.action}</p>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="flex items-center gap-1 text-[#a3a3a3] text-xs">
                      <User size={11} /> {req.user}
                    </span>
                    <span className="flex items-center gap-1 text-[#d4d0ca] text-xs">
                      <Clock size={11} />
                      {new Date(req.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded uppercase ${STATUS_BG[s]} ${STATUS_STYLES[s]}`}>
                    {s}
                  </span>
                  {isPending && (isExpanded ? <ChevronUp size={14} className="text-[#a3a3a3]" /> : <ChevronDown size={14} className="text-[#a3a3a3]" />)}
                </div>
              </button>

              {isExpanded && isPending && (
                <div className="px-5 py-4 border-t border-[#f3f1ec] flex items-center gap-3">
                  <button
                    onClick={() => handleAction(req.id, 'approved')}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-500 text-white rounded-lg text-sm font-semibold hover:bg-emerald-600 transition-colors"
                  >
                    <CheckCircle size={13} /> Approve
                  </button>
                  <button
                    onClick={() => handleAction(req.id, 'rejected')}
                    className="flex items-center gap-2 px-4 py-2 bg-white border border-[#dc2626]/30 text-[#dc2626] rounded-lg text-sm font-semibold hover:bg-red-500/5 transition-colors"
                  >
                    <XCircle size={13} /> Reject
                  </button>
                  <button className="flex items-center gap-2 px-4 py-2 text-[#525252] rounded-lg text-sm hover:bg-[#f3f1ec] transition-colors ml-auto">
                    <MessageSquare size={13} /> Add Note
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}