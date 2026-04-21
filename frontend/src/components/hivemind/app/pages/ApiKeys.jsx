import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Key, Plus, Copy, Check, Trash2, Shield, AlertTriangle,
  Globe, Brain, Wrench, ShieldCheck, Zap, CheckCircle2, XCircle,
} from 'lucide-react';
import apiClient from '../shared/api-client';
import { useApiQuery, useCopyToClipboard } from '../shared/hooks';

// ── Scope definitions ───────────────────────────────────────────────
const ALL_SCOPES = [
  { id: 'memory:read',  label: 'Memory Read',  icon: Brain,       group: 'core',  description: 'Read memories and search' },
  { id: 'memory:write', label: 'Memory Write', icon: Brain,       group: 'core',  description: 'Create, update, delete memories' },
  { id: 'mcp',          label: 'MCP Access',   icon: Wrench,      group: 'core',  description: 'Model Context Protocol tools' },
  { id: 'web_search',   label: 'Web Search',   icon: Globe,       group: 'web',   description: 'Search the web via async jobs' },
  { id: 'web_crawl',    label: 'Web Crawl',    icon: Globe,       group: 'web',   description: 'Crawl and extract web pages' },
  { id: 'web_admin',    label: 'Web Admin',    icon: ShieldCheck, group: 'admin', description: 'View admin metrics and telemetry' },
];

// ── Scope badge display ─────────────────────────────────────────────
function ScopeBadge({ scope, size = 'sm' }) {
  const def = ALL_SCOPES.find(s => s.id === scope);
  const colorMap = { core: '#117dff', web: '#16a34a', admin: '#d97706' };
  const color = colorMap[def?.group] || '#a3a3a3';
  const label = def?.label || scope;
  const px = size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center ${px} rounded-md font-semibold font-mono uppercase tracking-wider border`}
      style={{ color, backgroundColor: `${color}10`, borderColor: `${color}20` }}
    >
      {label}
    </span>
  );
}

// ── Test Access button ──────────────────────────────────────────────
function TestAccessButton({ rawKey }) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState(null); // 'success' | 'error'

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      // Temporarily use this key to hit health endpoint
      const prev = apiClient.getApiKey?.() || null;
      apiClient.setApiKey(rawKey);
      await apiClient.getHealth();
      setResult('success');
      if (prev) apiClient.setApiKey(prev);
    } catch {
      setResult('error');
    } finally {
      setTesting(false);
    }
  };

  return (
    <button
      onClick={handleTest}
      disabled={testing}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-['Space_Grotesk'] font-medium transition-all border border-[#e3e0db] hover:border-[#117dff]/20 bg-white text-[#525252] hover:text-[#0a0a0a] disabled:opacity-50"
    >
      {testing ? (
        <div className="w-3 h-3 border-2 border-[#117dff] border-t-transparent rounded-full animate-spin" />
      ) : result === 'success' ? (
        <><CheckCircle2 size={13} className="text-[#16a34a]" /> Connected</>
      ) : result === 'error' ? (
        <><XCircle size={13} className="text-[#dc2626]" /> Failed</>
      ) : (
        <><Zap size={13} /> Test Access</>
      )}
    </button>
  );
}

// ── Key Created Banner ──────────────────────────────────────────────
function KeyCreatedBanner({ rawKey, scopes, onDismiss }) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mb-6 overflow-hidden"
    >
      <div className="bg-[#faf9f4] border border-[#117dff]/30 rounded-xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="flex items-start gap-3 mb-3">
          <AlertTriangle size={18} className="text-[#117dff] mt-0.5 shrink-0" />
          <div>
            <p className="text-[#117dff] text-sm font-semibold font-['Space_Grotesk']">
              Save your API key now
            </p>
            <p className="text-[#525252] text-xs mt-1 font-['Space_Grotesk']">
              This is the only time you will see this key. Copy it and store it securely.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 bg-white border border-[#e3e0db] rounded-lg p-3">
          <code className="flex-1 text-[#117dff] text-sm font-mono break-all select-all">
            {rawKey}
          </code>
          <button
            onClick={() => copy(rawKey)}
            className="shrink-0 p-2 rounded-lg hover:bg-[#f3f1ec] transition-colors"
            title="Copy to clipboard"
          >
            {copied ? (
              <Check size={16} className="text-[#117dff]" />
            ) : (
              <Copy size={16} className="text-[#525252]" />
            )}
          </button>
        </div>

        {/* Scopes applied */}
        {scopes?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            <span className="text-[10px] text-[#a3a3a3] font-mono mr-1 self-center">SCOPES:</span>
            {scopes.map(s => <ScopeBadge key={s} scope={s} />)}
          </div>
        )}

        <div className="flex items-center gap-3 mt-3">
          <TestAccessButton rawKey={rawKey} />
          <button
            onClick={onDismiss}
            className="text-[#a3a3a3] hover:text-[#525252] text-xs font-mono transition-colors"
          >
            I've saved the key — dismiss
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ── Revoke Confirmation ─────────────────────────────────────────────
function RevokeConfirmation({ keyLabel, onConfirm, onCancel, revoking }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="flex items-center gap-3 bg-red-500/10 border border-red-500/20 rounded-lg p-3"
    >
      <AlertTriangle size={16} className="text-[#dc2626] shrink-0" />
      <p className="text-[#dc2626] text-xs font-['Space_Grotesk'] flex-1">
        Revoke <span className="font-semibold">"{keyLabel}"</span>? This cannot be undone.
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onCancel}
          disabled={revoking}
          className="px-3 py-1.5 text-xs text-[#525252] hover:text-[#0a0a0a] font-['Space_Grotesk'] transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={revoking}
          className="px-3 py-1.5 text-xs bg-red-500/20 hover:bg-red-500/30 text-[#dc2626] font-semibold rounded-lg font-['Space_Grotesk'] transition-colors disabled:opacity-40"
        >
          {revoking ? (
            <div className="w-3 h-3 border-2 border-[#dc2626] border-t-transparent rounded-full animate-spin" />
          ) : (
            'Revoke'
          )}
        </button>
      </div>
    </motion.div>
  );
}

// ── Key Row ─────────────────────────────────────────────────────────
function KeyRow({ apiKey, onRevoke }) {
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const isRevoked = apiKey.status === 'revoked';

  const handleRevoke = async () => {
    setRevoking(true);
    try {
      await onRevoke(apiKey.id);
    } finally {
      setRevoking(false);
      setConfirmingRevoke(false);
    }
  };

  const createdDate = new Date(apiKey.created_at || apiKey.createdAt).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

  const scopes = apiKey.scopes || [];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="bg-white border border-[#e3e0db] rounded-xl p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)]"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
            isRevoked
              ? 'bg-[#f3f1ec] border border-[#e3e0db]'
              : 'bg-[#117dff]/10 border border-[#117dff]/20'
          }`}>
            <Key size={14} className={isRevoked ? 'text-[#d4d0ca]' : 'text-[#117dff]'} />
          </div>
          <div className="min-w-0">
            <p className={`text-sm font-semibold font-['Space_Grotesk'] truncate ${
              isRevoked ? 'text-[#a3a3a3]' : 'text-[#0a0a0a]'
            }`}>
              {apiKey.name || apiKey.label}
            </p>
            <p className={`text-xs font-mono mt-0.5 ${
              isRevoked ? 'text-[#e3e0db]' : 'text-[#525252]'
            }`}>
              {apiKey.key_prefix || apiKey.keyPrefix || 'hm_...'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 shrink-0">
          <span className="text-xs font-mono text-[#a3a3a3] hidden sm:block">
            {createdDate}
          </span>

          {isRevoked ? (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold font-mono uppercase tracking-wider bg-red-500/10 text-[#dc2626]/60 border border-red-500/10">
              Revoked
            </span>
          ) : (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold font-mono uppercase tracking-wider bg-emerald-500/10 text-[#16a34a] border border-emerald-500/20">
              Active
            </span>
          )}

          {!isRevoked && (
            <button
              onClick={() => setConfirmingRevoke(true)}
              className="p-1.5 rounded-lg text-[#d4d0ca] hover:text-[#dc2626] hover:bg-red-50 transition-colors"
              title="Revoke key"
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Scope badges */}
      {scopes.length > 0 && !isRevoked && (
        <div className="flex flex-wrap gap-1 mt-2.5 ml-11">
          {scopes.map(s => <ScopeBadge key={s} scope={s} />)}
        </div>
      )}

      <AnimatePresence>
        {confirmingRevoke && (
          <div className="mt-3">
            <RevokeConfirmation
              keyLabel={apiKey.name || apiKey.label}
              onConfirm={handleRevoke}
              onCancel={() => setConfirmingRevoke(false)}
              revoking={revoking}
            />
          </div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────
export default function ApiKeysPage() {
  const DEFAULT_SCOPES = ['memory:read', 'memory:write', 'mcp', 'web_search', 'web_crawl', 'web_admin'];
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [newlyCreatedKey, setNewlyCreatedKey] = useState(null);
  const [newlyCreatedScopes, setNewlyCreatedScopes] = useState([]);

  const {
    data: keys,
    loading,
    error: fetchError,
    refetch,
  } = useApiQuery(() => apiClient.listApiKeys(), []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!label.trim()) return;

    setCreating(true);
    setCreateError(null);
    try {
      const result = await apiClient.createApiKey(label.trim(), { scopes: DEFAULT_SCOPES });
      setNewlyCreatedKey(result.api_key);
      setNewlyCreatedScopes([...DEFAULT_SCOPES]);
      apiClient.setApiKey(result.api_key);
      setLabel('');
      refetch();
    } catch (err) {
      setCreateError(err.response?.data?.error || err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id) => {
    await apiClient.revokeApiKey(id);
    refetch();
  };

  const keyList = Array.isArray(keys) ? keys : keys?.keys || [];

  return (
    <div className="min-h-screen bg-[#faf9f4] p-6 md:p-10">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-[#117dff]/10 border border-[#117dff]/20 flex items-center justify-center">
              <Key size={20} className="text-[#117dff]" />
            </div>
            <h1 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk']">
              API Keys
            </h1>
          </div>
          <p className="text-[#525252] text-sm font-['Space_Grotesk'] ml-[52px]">
            Create and manage authentication keys with granular permissions.
          </p>
        </motion.div>

        {/* Security Notice */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="mb-6"
        >
          <div className="flex items-start gap-3 bg-white border border-[#e3e0db] rounded-xl p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Shield size={16} className="text-[#a3a3a3] mt-0.5 shrink-0" />
            <p className="text-[#525252] text-xs font-['Space_Grotesk'] leading-relaxed">
              API keys authenticate requests to the HIVEMIND Core API. Each key is scoped to your
              organization with specific permissions. Keep keys secret — revoke any key you suspect
              has been compromised.
            </p>
          </div>
        </motion.div>

        {/* Create Key Form */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mb-8"
        >
          <div className="bg-white border border-[#e3e0db] rounded-xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h2 className="text-[#0a0a0a] text-sm font-semibold font-['Space_Grotesk'] mb-4">
              Create a new key
            </h2>
            <form onSubmit={handleCreate} className="space-y-4">
              {/* Label */}
              <div>
                <label className="block text-[#525252] text-xs font-mono mb-2 uppercase tracking-wider">
                  Label
                </label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder='e.g. "Production Key", "Dev Key"'
                  maxLength={64}
                  className="w-full bg-transparent border border-[#e3e0db] rounded-xl py-2.5 px-4 text-[#0a0a0a] text-sm font-['Space_Grotesk'] placeholder:text-[#a3a3a3] focus:outline-none focus:border-[#117dff]/40 transition-colors"
                />
              </div>

              {/* All keys get full access by default */}
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-[#a3a3a3] font-mono mr-1 self-center">SCOPES:</span>
                {DEFAULT_SCOPES.map(s => <ScopeBadge key={s} scope={s} />)}
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={!label.trim() || creating}
                className="flex items-center gap-2 bg-[#117dff] hover:bg-[#0066e0] disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 px-5 rounded-xl transition-all text-sm font-['Space_Grotesk']"
              >
                {creating ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <>
                    <Plus size={16} />
                    Create Key
                  </>
                )}
              </button>
            </form>

            {createError && (
              <p className="text-[#dc2626] text-xs mt-3 font-mono">{createError}</p>
            )}
          </div>
        </motion.div>

        {/* Newly Created Key Banner */}
        <AnimatePresence>
          {newlyCreatedKey && (
            <KeyCreatedBanner
              rawKey={newlyCreatedKey}
              scopes={newlyCreatedScopes}
              onDismiss={() => { setNewlyCreatedKey(null); setNewlyCreatedScopes([]); }}
            />
          )}
        </AnimatePresence>

        {/* Keys List */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
        >
          <h2 className="text-[#525252] text-xs font-mono mb-3 uppercase tracking-wider">
            Existing Keys ({loading ? '...' : keyList.length})
          </h2>

          {fetchError && (
            <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4">
              <AlertTriangle size={16} className="text-[#dc2626] shrink-0" />
              <p className="text-[#dc2626] text-xs font-['Space_Grotesk']">
                Failed to load keys: {fetchError}
              </p>
            </div>
          )}

          {loading && !keys ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="bg-white border border-[#e3e0db] rounded-xl p-4 animate-pulse shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-[#f3f1ec]" />
                    <div className="flex-1">
                      <div className="h-4 w-32 bg-[#f3f1ec] rounded" />
                      <div className="h-3 w-20 bg-[#f3f1ec] rounded mt-1.5" />
                    </div>
                    <div className="h-5 w-14 bg-[#f3f1ec] rounded-md" />
                  </div>
                </div>
              ))}
            </div>
          ) : keyList.length === 0 ? (
            <div className="bg-white border border-[#e3e0db] rounded-xl p-10 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <Key size={24} className="text-[#e3e0db] mx-auto mb-3" />
              <p className="text-[#a3a3a3] text-sm font-['Space_Grotesk']">
                No API keys yet. Create one above to get started.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <AnimatePresence mode="popLayout">
                {keyList.map((k) => (
                  <KeyRow key={k.id} apiKey={k} onRevoke={handleRevoke} />
                ))}
              </AnimatePresence>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
