import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Key, ArrowRight } from 'lucide-react';
import { useAuth } from '../auth/AuthProvider';

/**
 * Contextual API key prompt — shown inline when a feature needs an API key.
 * Instead of blocking the entire app, this appears only on pages that need it.
 */
export default function ApiKeyPrompt({ feature = 'this feature' }) {
  const { hasApiKey } = useAuth();
  const navigate = useNavigate();

  // Don't show if user already has a key
  if (hasApiKey) return null;

  return (
    <div className="mb-6 flex items-center gap-4 px-5 py-4 rounded-xl bg-[#fffbeb] border border-[#fde68a] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="w-10 h-10 rounded-xl bg-[#f59e0b]/10 flex items-center justify-center shrink-0">
        <Key size={18} className="text-[#f59e0b]" />
      </div>
      <div className="flex-1">
        <p className="text-[#92400e] text-sm font-semibold font-['Space_Grotesk']">
          API Key required for {feature}
        </p>
        <p className="text-[#a3752e] text-xs font-['Space_Grotesk'] mt-0.5">
          Generate an API key to connect external clients and use the API.
        </p>
      </div>
      <button
        onClick={() => navigate('/hivemind/app/keys')}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#f59e0b] hover:bg-[#d97706] text-white text-xs font-semibold font-['Space_Grotesk'] transition-all shrink-0"
      >
        Generate Key
        <ArrowRight size={12} />
      </button>
    </div>
  );
}
