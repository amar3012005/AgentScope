import React, { useState, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Settings as SettingsIcon,
  Building2,
  Globe,
  Copy,
  Check,
  AlertTriangle,
  Trash2,
  ExternalLink,
  Info,
} from 'lucide-react';
import apiClient from '../shared/api-client';
import { useAuth } from '../auth/AuthProvider';

const HIVEMIND_VERSION = '1.0.0';

const stagger = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' } },
};

// ─── Copy button with per-field tracking ────────────────────────────────────
function CopyButton({ value, field, copiedField, onCopy }) {
  const isCopied = copiedField === field;
  return (
    <button
      onClick={() => onCopy(value, field)}
      className="ml-2 p-1.5 rounded-lg hover:bg-[#117dff]/10 transition-colors group flex-shrink-0"
      title="Copy to clipboard"
    >
      {isCopied ? (
        <Check size={14} className="text-[#117dff]" />
      ) : (
        <Copy size={14} className="text-[#a3a3a3] group-hover:text-[#117dff] transition-colors" />
      )}
    </button>
  );
}

// ─── Read-only field row ────────────────────────────────────────────────────
function ReadOnlyField({ label, value, field, copiedField, onCopy }) {
  return (
    <div>
      <label className="block text-[#525252] text-[11px] font-mono uppercase tracking-wider mb-1.5">
        {label}
      </label>
      <div className="flex items-center bg-[#faf9f4] border border-[#e3e0db] rounded-xl px-3 py-2.5">
        <span className="text-[#525252] text-sm font-mono truncate flex-1 select-all">
          {value || '\u2014'}
        </span>
        {value && (
          <CopyButton
            value={value}
            field={field}
            copiedField={copiedField}
            onCopy={onCopy}
          />
        )}
      </div>
    </div>
  );
}

// ─── Section card wrapper ───────────────────────────────────────────────────
function SectionCard({ children, className = '' }) {
  return (
    <motion.div
      variants={fadeUp}
      className={`bg-white backdrop-blur-xl border border-[#e3e0db] rounded-xl p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${className}`}
    >
      {children}
    </motion.div>
  );
}

function SectionHeader({ icon: Icon, title, description }) {
  return (
    <div className="flex items-start gap-3 mb-5">
      <div className="w-9 h-9 rounded-xl bg-[#117dff]/10 border border-[#117dff]/20 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Icon size={18} className="text-[#117dff]" />
      </div>
      <div>
        <h3 className="text-[#0a0a0a] text-base font-semibold font-['Space_Grotesk']">{title}</h3>
        {description && (
          <p className="text-[#525252] text-sm mt-0.5">{description}</p>
        )}
      </div>
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function Settings() {
  const { user, org, logout } = useAuth();
  const [copiedField, setCopiedField] = useState(null);
  const [revoking, setRevoking] = useState(false);
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false);
  const timeoutRef = useRef(null);

  const controlPlaneUrl = apiClient.controlPlane.defaults.baseURL;
  const coreApiUrl = apiClient.core.defaults.baseURL;

  const handleCopy = useCallback(async (text, field) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopiedField(field);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setCopiedField(null), 2000);
  }, []);

  const handleRevokeAllKeys = useCallback(async () => {
    setRevoking(true);
    try {
      await apiClient.controlPlane.delete('/v1/keys');
      setShowRevokeConfirm(false);
    } catch {
      // Silently handle — user stays on page
    } finally {
      setRevoking(false);
    }
  }, []);

  const handleSignOutAll = useCallback(async () => {
    await logout();
  }, [logout]);

  const createdDate = org?.created_at
    ? new Date(org.created_at).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '\u2014';

  return (
    <div className="min-h-full">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk'] flex items-center gap-2.5">
          <SettingsIcon size={24} className="text-[#117dff]" />
          Settings
        </h1>
        <p className="text-[#525252] text-sm mt-1 font-['Space_Grotesk']">
          Workspace configuration and connection details
        </p>
      </div>

      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="space-y-6 max-w-3xl"
      >
        {/* ── Workspace Info ──────────────────────────────────────── */}
        <SectionCard>
          <SectionHeader
            icon={Building2}
            title="Workspace Info"
            description="Your organization and workspace details"
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[#525252] text-[11px] font-mono uppercase tracking-wider mb-1.5">
                Organization
              </label>
              <p className="text-[#0a0a0a] text-sm font-['Space_Grotesk'] font-medium">
                {org?.name || '\u2014'}
              </p>
            </div>
            <div>
              <label className="block text-[#525252] text-[11px] font-mono uppercase tracking-wider mb-1.5">
                Created
              </label>
              <p className="text-[#525252] text-sm font-['Space_Grotesk']">
                {createdDate}
              </p>
            </div>
            <div>
              <label className="block text-[#525252] text-[11px] font-mono uppercase tracking-wider mb-1.5">
                Your Role
              </label>
              <span className="inline-block text-[#117dff] text-xs font-mono bg-[#117dff]/10 border border-[#117dff]/20 rounded-md px-2 py-1">
                {user?.role || 'owner'}
              </span>
            </div>
            <div>
              <label className="block text-[#525252] text-[11px] font-mono uppercase tracking-wider mb-1.5">
                Core API URL
              </label>
              <p className="text-[#525252] text-sm font-mono truncate" title={coreApiUrl}>
                {coreApiUrl || '\u2014'}
              </p>
            </div>
          </div>
        </SectionCard>

        {/* ── Connection Details ──────────────────────────────────── */}
        <SectionCard>
          <SectionHeader
            icon={Globe}
            title="Connection Details"
            description="Use these values to configure API clients and integrations"
          />
          <div className="space-y-3">
            <ReadOnlyField
              label="Control Plane URL"
              value={controlPlaneUrl}
              field="controlPlane"
              copiedField={copiedField}
              onCopy={handleCopy}
            />
            <ReadOnlyField
              label="Core API Base URL"
              value={coreApiUrl}
              field="coreApi"
              copiedField={copiedField}
              onCopy={handleCopy}
            />
            <ReadOnlyField
              label="User ID"
              value={user?.id}
              field="userId"
              copiedField={copiedField}
              onCopy={handleCopy}
            />
            <ReadOnlyField
              label="Org ID"
              value={org?.id}
              field="orgId"
              copiedField={copiedField}
              onCopy={handleCopy}
            />
          </div>
        </SectionCard>

        {/* ── Danger Zone ─────────────────────────────────────────── */}
        <SectionCard className="!border-red-200 !bg-red-50">
          <div className="flex items-start gap-3 mb-5">
            <div className="w-9 h-9 rounded-xl bg-red-500/10 border border-red-200 flex items-center justify-center flex-shrink-0 mt-0.5">
              <AlertTriangle size={18} className="text-[#dc2626]" />
            </div>
            <div>
              <h3 className="text-[#dc2626] text-base font-semibold font-['Space_Grotesk']">
                Danger Zone
              </h3>
              <p className="text-[#525252] text-sm mt-0.5">
                These actions are destructive and cannot be undone.
              </p>
            </div>
          </div>

          <div className="space-y-4">
            {/* Sign Out All Sessions */}
            <div className="flex items-center justify-between bg-white border border-red-200 rounded-xl px-4 py-3">
              <div>
                <p className="text-[#0a0a0a] text-sm font-['Space_Grotesk'] font-medium">
                  Sign Out of All Sessions
                </p>
                <p className="text-[#a3a3a3] text-xs mt-0.5">
                  Invalidates all active sessions across devices.
                </p>
              </div>
              <button
                onClick={handleSignOutAll}
                className="flex items-center gap-1.5 text-[#dc2626] hover:text-[#dc2626] text-xs font-mono bg-red-500/10 hover:bg-red-50 border border-red-200 rounded-lg px-3 py-2 transition-colors flex-shrink-0 ml-4"
              >
                Sign Out
              </button>
            </div>

            {/* Revoke All API Keys */}
            <div className="flex items-center justify-between bg-white border border-red-200 rounded-xl px-4 py-3">
              <div>
                <p className="text-[#0a0a0a] text-sm font-['Space_Grotesk'] font-medium">
                  Revoke All API Keys
                </p>
                <p className="text-[#a3a3a3] text-xs mt-0.5">
                  All existing API keys will stop working immediately.
                </p>
              </div>
              {showRevokeConfirm ? (
                <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                  <button
                    onClick={() => setShowRevokeConfirm(false)}
                    className="text-[#525252] hover:text-[#525252] text-xs font-mono px-3 py-2 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleRevokeAllKeys}
                    disabled={revoking}
                    className="flex items-center gap-1.5 text-white bg-red-600 hover:bg-red-500 disabled:opacity-50 text-xs font-mono rounded-lg px-3 py-2 transition-colors"
                  >
                    {revoking ? (
                      <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Trash2 size={12} />
                    )}
                    Confirm Revoke
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowRevokeConfirm(true)}
                  className="flex items-center gap-1.5 text-[#dc2626] hover:text-[#dc2626] text-xs font-mono bg-red-500/10 hover:bg-red-50 border border-red-200 rounded-lg px-3 py-2 transition-colors flex-shrink-0 ml-4"
                >
                  <Trash2 size={12} />
                  Revoke All
                </button>
              )}
            </div>
          </div>
        </SectionCard>

        {/* ── About ───────────────────────────────────────────────── */}
        <SectionCard>
          <SectionHeader
            icon={Info}
            title="About HIVEMIND"
            description="Persistent memory engine for AI agents"
          />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[#525252] text-xs font-mono uppercase tracking-wider">
                Version
              </span>
              <span className="text-[#525252] text-sm font-mono">{HIVEMIND_VERSION}</span>
            </div>
            <div className="border-t border-[#eae7e1] pt-3">
              <p className="text-[#a3a3a3] text-sm leading-relaxed mb-4">
                HIVEMIND is a persistent memory engine that gives AI agents long-term recall,
                semantic search, and cross-session context. Memories are stored, versioned,
                and retrievable across all connected clients.
              </p>
              <div className="flex items-center gap-4">
                <a
                  href="https://docs.hivemind.dev"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-[#117dff] hover:text-[#0066e0] text-xs font-mono transition-colors"
                >
                  Documentation
                  <ExternalLink size={11} />
                </a>
                <a
                  href="https://hivemind.dev/support"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-[#117dff] hover:text-[#0066e0] text-xs font-mono transition-colors"
                >
                  Support
                  <ExternalLink size={11} />
                </a>
              </div>
            </div>
          </div>
        </SectionCard>
      </motion.div>
    </div>
  );
}
