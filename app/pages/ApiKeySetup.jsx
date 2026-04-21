import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Hexagon, Key, Copy, Check, ArrowRight, AlertTriangle,
  Brain, Globe, ShieldCheck, Zap, CheckCircle2, XCircle,
} from 'lucide-react';
import apiClient from '../shared/api-client';
import { useAuth } from '../auth/AuthProvider';
import { useCopyToClipboard } from '../shared/hooks';

const SCOPE_PRESETS = [
  {
    id: 'standard',
    label: 'Standard',
    description: 'Memory read/write + MCP tools',
    scopes: ['memory:read', 'memory:write', 'mcp'],
    icon: Brain,
  },
  {
    id: 'web',
    label: 'Web Intelligence',
    description: 'Standard + web search & crawl',
    scopes: ['memory:read', 'memory:write', 'mcp', 'web_search', 'web_crawl'],
    icon: Globe,
  },
  {
    id: 'admin',
    label: 'Admin',
    description: 'Full access including admin metrics',
    scopes: ['memory:read', 'memory:write', 'mcp', 'web_search', 'web_crawl', 'web_admin'],
    icon: ShieldCheck,
  },
];

function TestAccessButton({ rawKey }) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState(null);

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      apiClient.setApiKey(rawKey);
      await apiClient.getHealth();
      setResult('success');
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
      className="flex items-center justify-center gap-2 w-full bg-[#f3f1ec] hover:bg-[#e3e0db] text-[#0a0a0a] font-semibold py-3 px-6 rounded-[4px] transition-all text-sm font-['Space_Grotesk'] border border-[#e3e0db] uppercase tracking-[0.075em] disabled:opacity-50"
    >
      {testing ? (
        <div className="w-4 h-4 border-2 border-[#0a0a0a] border-t-transparent rounded-full animate-spin" />
      ) : result === 'success' ? (
        <><CheckCircle2 size={16} className="text-[#16a34a]" /> Connected Successfully</>
      ) : result === 'error' ? (
        <><XCircle size={16} className="text-[#dc2626]" /> Connection Failed</>
      ) : (
        <><Zap size={16} /> Test Access</>
      )}
    </button>
  );
}

/**
 * First-time API key setup — shown when bootstrap.onboarding.has_api_key is false.
 * Now with scope preset selection.
 */
export default function ApiKeySetup() {
  const { user, refresh, hasApiKey } = useAuth();
  const { copied, copy } = useCopyToClipboard();
  const [step, setStep] = useState('create'); // 'create' | 'show'
  const [creating, setCreating] = useState(false);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState(null);
  const [rawKey, setRawKey] = useState(null);
  const [existingKey, setExistingKey] = useState('');
  const [selectedPreset, setSelectedPreset] = useState('admin');

  const activePreset = SCOPE_PRESETS.find(p => p.id === selectedPreset);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const result = await apiClient.createApiKey('Primary API Key', {
        scopes: activePreset.scopes,
      });
      setRawKey(result.api_key);
      apiClient.setApiKey(result.api_key);
      setStep('show');
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleUseExisting = async () => {
    if (!existingKey.trim()) return;
    setActivating(true);
    setError(null);
    try {
      apiClient.setApiKey(existingKey.trim());
      await apiClient.getProfile();
      refresh();
    } catch (err) {
      apiClient.clearApiKey();
      setError(err.response?.data?.error || 'That API key was rejected by the core API.');
    } finally {
      setActivating(false);
    }
  };

  const handleContinue = () => {
    refresh();
  };

  return (
    <div className="min-h-screen bg-[#faf9f4] flex items-center justify-center">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-[#117dff]/[0.03] blur-[100px]" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 w-full max-w-lg mx-4"
      >
        <div className="bg-white backdrop-blur-xl border border-[#e3e0db] rounded-2xl p-8 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-[#117dff]/10 border border-[#117dff]/20 flex items-center justify-center">
              <Hexagon size={22} className="text-[#117dff]" />
            </div>
            <span className="text-[#0a0a0a] text-lg font-bold font-['Space_Grotesk']">HIVEMIND</span>
          </div>

          {step === 'create' && (
            <>
              <h2 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk'] mb-2">
                {hasApiKey ? 'Connect your core API key' : 'Create your API key'}
              </h2>
              <p className="text-[#525252] text-sm mb-6 leading-relaxed">
                Hi {user?.display_name || user?.email || 'there'} — {hasApiKey
                  ? 'paste an existing HIVEMIND Core API key or create a replacement key for this browser.'
                  : 'choose the capabilities for your API key.'}
              </p>

              {error && (
                <div className="mb-4 flex items-start gap-2 bg-red-50 border border-red-200 rounded-xl p-3">
                  <AlertTriangle size={14} className="text-[#dc2626] mt-0.5 shrink-0" />
                  <p className="text-[#dc2626] text-xs font-mono">{error}</p>
                </div>
              )}

              {hasApiKey && (
                <div className="mb-5">
                  <label className="block text-[#a3a3a3] text-xs font-mono mb-2 uppercase tracking-wider">
                    Existing Core API Key
                  </label>
                  <div className="flex flex-col gap-3">
                    <input
                      type="password"
                      value={existingKey}
                      onChange={(e) => setExistingKey(e.target.value)}
                      placeholder="hm_..."
                      className="w-full bg-transparent border border-[#e3e0db] rounded-[6px] py-3 px-4 text-[#0a0a0a] text-sm font-mono placeholder:text-[#d4d0ca] focus:outline-none focus:border-[#117dff]/40 transition-colors"
                    />
                    <button
                      onClick={handleUseExisting}
                      disabled={activating || !existingKey.trim()}
                      className="w-full flex items-center justify-center gap-2 bg-[#f3f1ec] hover:bg-[#e3e0db] disabled:opacity-40 text-[#0a0a0a] font-semibold py-3 px-6 rounded-[4px] transition-all text-sm font-['Space_Grotesk'] border border-[#e3e0db] uppercase tracking-[0.075em]"
                    >
                      {activating ? (
                        <div className="w-4 h-4 border-2 border-[#0a0a0a] border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <>
                          <Key size={16} />
                          Use Existing Key
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {/* Scope presets */}
              <div className="mb-5">
                <label className="block text-[#a3a3a3] text-xs font-mono mb-3 uppercase tracking-wider">
                  Key Type
                </label>
                <div className="space-y-2">
                  {SCOPE_PRESETS.map(preset => {
                    const Icon = preset.icon;
                    const isActive = selectedPreset === preset.id;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => setSelectedPreset(preset.id)}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-all border ${
                          isActive
                            ? 'bg-[#117dff]/5 border-[#117dff]/30'
                            : 'bg-white border-[#e3e0db] hover:border-[#117dff]/15'
                        }`}
                      >
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                          isActive ? 'border-[#117dff]' : 'border-[#e3e0db]'
                        }`}>
                          {isActive && <div className="w-2 h-2 rounded-full bg-[#117dff]" />}
                        </div>
                        <Icon size={16} className={isActive ? 'text-[#117dff]' : 'text-[#a3a3a3]'} />
                        <div className="flex-1 min-w-0">
                          <p className={`text-sm font-semibold font-['Space_Grotesk'] ${isActive ? 'text-[#0a0a0a]' : 'text-[#525252]'}`}>
                            {preset.label}
                          </p>
                          <p className="text-[11px] text-[#a3a3a3] font-['Space_Grotesk']">
                            {preset.description}
                          </p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <button
                onClick={handleCreate}
                disabled={creating}
                className="w-full flex items-center justify-center gap-2 bg-[#117dff] hover:bg-[#0e6fe0] disabled:opacity-40 text-white font-semibold py-3 px-6 rounded-[4px] transition-all text-sm font-['Space_Grotesk'] group cursor-pointer border-none uppercase tracking-[0.075em]"
              >
                {creating ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <>
                    <Key size={16} />
                    {hasApiKey ? 'Create Replacement Key' : 'Generate API Key'}
                  </>
                )}
              </button>
            </>
          )}

          {step === 'show' && rawKey && (
            <>
              <h2 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk'] mb-2">
                Your API key
              </h2>

              {/* Warning */}
              <div className="flex items-start gap-2 mb-4">
                <AlertTriangle size={14} className="text-[#d97706] mt-0.5 shrink-0" />
                <p className="text-[#d97706] text-xs font-['Space_Grotesk'] leading-relaxed">
                  Copy this key now. It will not be shown again.
                </p>
              </div>

              {/* Key display */}
              <div className="flex items-center gap-2 bg-[#f3f1ec] border border-[#117dff]/30 rounded-[6px] p-4 mb-4">
                <code className="flex-1 text-[#117dff] text-sm font-mono break-all select-all">
                  {rawKey}
                </code>
                <button
                  onClick={() => copy(rawKey)}
                  className="shrink-0 p-2 rounded-lg hover:bg-[#e3e0db] transition-colors cursor-pointer bg-transparent border-none"
                >
                  {copied ? (
                    <Check size={16} className="text-[#16a34a]" />
                  ) : (
                    <Copy size={16} className="text-[#a3a3a3]" />
                  )}
                </button>
              </div>

              {/* Scopes applied */}
              <div className="flex flex-wrap items-center gap-1.5 mb-4">
                <span className="text-[10px] text-[#a3a3a3] font-mono uppercase">Scopes:</span>
                {activePreset.scopes.map(s => (
                  <span
                    key={s}
                    className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold font-mono uppercase tracking-wider bg-[#117dff]/10 text-[#117dff] border border-[#117dff]/20"
                  >
                    {s}
                  </span>
                ))}
              </div>

              {/* Test Access */}
              <div className="mb-4">
                <TestAccessButton rawKey={rawKey} />
              </div>

              {/* Continue */}
              <button
                onClick={handleContinue}
                className="w-full flex items-center justify-center gap-2 bg-[#117dff] hover:bg-[#0e6fe0] text-white font-semibold py-3 px-6 rounded-[4px] transition-all text-sm font-['Space_Grotesk'] group cursor-pointer border-none uppercase tracking-[0.075em]"
              >
                Continue to Dashboard
                <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
              </button>
            </>
          )}
        </div>

        {/* Progress indicator */}
        <div className="flex items-center justify-center gap-2 mt-6">
          <div className="w-2 h-2 rounded-full bg-[#117dff]" />
          <div className="w-8 h-0.5 bg-[#117dff]/30" />
          <div className={`w-2 h-2 rounded-full ${step === 'show' ? 'bg-[#117dff]' : 'bg-[#e3e0db]'}`} />
          <div className="w-8 h-0.5 bg-[#e3e0db]" />
          <div className="w-2 h-2 rounded-full bg-[#e3e0db]" />
        </div>
        <div className="flex items-center justify-center gap-8 mt-2">
          <span className="text-[10px] text-[#117dff]/60 font-mono">Org</span>
          <span className={`text-[10px] font-mono ${step === 'show' ? 'text-[#117dff]/60' : 'text-[#a3a3a3]'}`}>Key</span>
          <span className="text-[10px] text-[#a3a3a3] font-mono">Dashboard</span>
        </div>
      </motion.div>
    </div>
  );
}
