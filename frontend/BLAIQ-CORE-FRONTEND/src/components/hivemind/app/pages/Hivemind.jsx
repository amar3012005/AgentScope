import React, { useState, useEffect, useCallback } from 'react';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';
import { LogOut, Zap, Shield, Lock, Check } from 'lucide-react';

export default function Hivemind() {
  const { isDayMode } = useBlaiqWorkspace();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const [formData, setFormData] = useState({
    api_key: '',
    org_id: '',
    user_id: '',
    base_url: 'https://core.hivemind.davinciai.eu:8050',
  });

  // Check credentials status on mount
  useEffect(() => {
    checkStatus();
  }, []);

  const checkStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/v1/hivemind/credentials/status', {
        headers: { Accept: 'application/json' },
      });
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
        setError(null);
      }
    } catch (err) {
      console.error('Status check failed:', err);
    }
  }, []);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSave = useCallback(async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/v1/hivemind/credentials/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to save credentials');
      }

      // Credentials saved
      setShowForm(false);
      setFormData({
        api_key: '',
        org_id: '',
        user_id: '',
        base_url: 'https://core.hivemind.davinciai.eu:8050',
      });
      await checkStatus();
    } catch (err) {
      setError(err.message || 'Failed to save credentials');
    } finally {
      setLoading(false);
    }
  }, [formData]);

  const handleDisconnect = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v1/hivemind/credentials/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (response.ok) {
        await checkStatus();
      } else {
        setError('Failed to disconnect');
      }
    } catch (err) {
      setError(err.message || 'Disconnect failed');
    } finally {
      setLoading(false);
    }
  }, [checkStatus]);

  return (
    <div className={`flex-1 p-8 overflow-auto ${isDayMode ? 'bg-white' : 'bg-[#0f0f0f]'}`}>
      <div className="max-w-3xl">
        {/* Header */}
        <div className="mb-8">
          <h1 className={`text-3xl font-bold mb-2 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
            HiveMind Configuration
          </h1>
          <p className={`text-sm ${isDayMode ? 'text-gray-600' : 'text-gray-400'}`}>
            Connect BLAIQ with HiveMind Enterprise to enable distributed memory and intelligence.
          </p>
        </div>

        {/* Status indicator */}
        {status && (
          <div className={`mb-6 p-4 rounded-lg border ${
            status.configured
              ? isDayMode
                ? 'border-emerald-200 bg-emerald-50'
                : 'border-emerald-900/30 bg-emerald-900/10'
              : isDayMode
              ? 'border-amber-200 bg-amber-50'
              : 'border-amber-900/30 bg-amber-900/10'
          }`}>
            <div className="flex items-center gap-3">
              <div className={`h-3 w-3 rounded-full ${status.configured ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              <div>
                <p className={`font-medium text-sm ${
                  status.configured
                    ? isDayMode ? 'text-emerald-900' : 'text-emerald-300'
                    : isDayMode ? 'text-amber-900' : 'text-amber-300'
                }`}>
                  {status.configured ? '✓ Connected' : 'Not Connected'}
                </p>
                {status.configured && (
                  <p className={`text-xs mt-1 ${isDayMode ? 'text-emerald-700' : 'text-emerald-400'}`}>
                    Org: <span className="font-mono">{status.org_id}</span>
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className={`mb-6 p-4 rounded-lg border-l-4 ${
            isDayMode
              ? 'border-red-400 bg-red-50 text-red-800'
              : 'border-red-500 bg-red-500/10 text-red-400'
          }`}>
            <p className="text-sm font-medium">{error}</p>
          </div>
        )}

        {/* Credentials form */}
        {showForm ? (
          <form onSubmit={handleSave} className={`p-6 rounded-lg border ${
            isDayMode
              ? 'border-gray-200 bg-gray-50'
              : 'border-gray-800 bg-gray-900/50'
          }`}>
            <h2 className={`text-lg font-semibold mb-4 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
              Enter HiveMind Credentials
            </h2>

            <div className="space-y-4">
              <div>
                <label className={`block text-sm font-medium mb-1 ${isDayMode ? 'text-gray-700' : 'text-gray-300'}`}>
                  API Key
                </label>
                <input
                  type="password"
                  name="api_key"
                  value={formData.api_key}
                  onChange={handleInputChange}
                  placeholder="hmk_live_..."
                  required
                  className={`w-full px-3 py-2 rounded-lg border font-mono text-sm ${
                    isDayMode
                      ? 'border-gray-300 bg-white text-gray-900'
                      : 'border-gray-700 bg-gray-800 text-gray-100'
                  }`}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className={`block text-sm font-medium mb-1 ${isDayMode ? 'text-gray-700' : 'text-gray-300'}`}>
                    Organization ID
                  </label>
                  <input
                    type="text"
                    name="org_id"
                    value={formData.org_id}
                    onChange={handleInputChange}
                    placeholder="9254abfe-8aae-4d51-..."
                    required
                    className={`w-full px-3 py-2 rounded-lg border font-mono text-sm ${
                      isDayMode
                        ? 'border-gray-300 bg-white text-gray-900'
                        : 'border-gray-700 bg-gray-800 text-gray-100'
                    }`}
                  />
                </div>

                <div>
                  <label className={`block text-sm font-medium mb-1 ${isDayMode ? 'text-gray-700' : 'text-gray-300'}`}>
                    User ID
                  </label>
                  <input
                    type="text"
                    name="user_id"
                    value={formData.user_id}
                    onChange={handleInputChange}
                    placeholder="e8df9371-632c-442f-..."
                    required
                    className={`w-full px-3 py-2 rounded-lg border font-mono text-sm ${
                      isDayMode
                        ? 'border-gray-300 bg-white text-gray-900'
                        : 'border-gray-700 bg-gray-800 text-gray-100'
                    }`}
                  />
                </div>
              </div>

              <div>
                <label className={`block text-sm font-medium mb-1 ${isDayMode ? 'text-gray-700' : 'text-gray-300'}`}>
                  Base URL (optional)
                </label>
                <input
                  type="url"
                  name="base_url"
                  value={formData.base_url}
                  onChange={handleInputChange}
                  placeholder="https://core.hivemind.davinciai.eu:8050"
                  className={`w-full px-3 py-2 rounded-lg border font-mono text-sm ${
                    isDayMode
                      ? 'border-gray-300 bg-white text-gray-900'
                      : 'border-gray-700 bg-gray-800 text-gray-100'
                  }`}
                />
              </div>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="submit"
                disabled={loading}
                className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                  loading
                    ? isDayMode
                      ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                      : 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    : isDayMode
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'bg-blue-500 text-white hover:bg-blue-600'
                }`}
              >
                <Check size={16} />
                {loading ? 'Saving...' : 'Save Credentials'}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className={`px-4 py-2 rounded-lg font-medium transition-all ${
                  isDayMode
                    ? 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className={`p-6 rounded-lg border ${
            isDayMode
              ? 'border-gray-200 bg-gray-50'
              : 'border-gray-800 bg-gray-900/50'
          }`}>
            {status?.configured ? (
              <div>
                <h2 className={`text-lg font-semibold mb-4 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
                  Connected Organization
                </h2>
                <p className={`text-sm mb-4 ${isDayMode ? 'text-gray-700' : 'text-gray-300'}`}>
                  Org ID: <span className="font-mono font-medium">{status.org_id}</span>
                </p>
                <div className="flex gap-3">
                  <button
                    onClick={() => setShowForm(true)}
                    className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                      isDayMode
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-blue-500 text-white hover:bg-blue-600'
                    }`}
                  >
                    <Shield size={16} />
                    Update Credentials
                  </button>
                  <button
                    onClick={handleDisconnect}
                    disabled={loading}
                    className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                      isDayMode
                        ? 'bg-red-100 text-red-600 hover:bg-red-200'
                        : 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                    }`}
                  >
                    <LogOut size={16} />
                    Disconnect
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-center py-4">
                <div className={`inline-flex items-center justify-center w-12 h-12 rounded-lg mb-4 ${
                  isDayMode ? 'bg-blue-100' : 'bg-blue-500/10'
                }`}>
                  <Zap size={24} className={isDayMode ? 'text-blue-600' : 'text-blue-400'} />
                </div>
                <h2 className={`text-lg font-semibold mb-2 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
                  Not Connected
                </h2>
                <p className={`text-sm mb-6 ${isDayMode ? 'text-gray-600' : 'text-gray-400'}`}>
                  Click below to add your HiveMind enterprise credentials.
                </p>
                <button
                  onClick={() => setShowForm(true)}
                  className={`px-6 py-3 rounded-lg font-semibold transition-all flex items-center gap-2 mx-auto ${
                    isDayMode
                      ? 'bg-blue-600 text-white hover:bg-blue-700'
                      : 'bg-blue-500 text-white hover:bg-blue-600'
                  }`}
                >
                  <Shield size={18} />
                  Connect to HiveMind
                </button>
              </div>
            )}
          </div>
        )}

        {/* Info panels */}
        <div className="mt-8 grid grid-cols-2 gap-4">
          <div className={`rounded-lg border p-4 ${
            isDayMode
              ? 'border-gray-200 bg-gray-50'
              : 'border-gray-800 bg-gray-900/50'
          }`}>
            <div className="flex items-start gap-3">
              <Lock size={18} className={isDayMode ? 'text-gray-600' : 'text-gray-400'} />
              <div>
                <h4 className={`font-semibold text-sm mb-1 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
                  Secure Storage
                </h4>
                <p className={`text-xs ${isDayMode ? 'text-gray-600' : 'text-gray-400'}`}>
                  Credentials stored in-memory for this session only.
                </p>
              </div>
            </div>
          </div>

          <div className={`rounded-lg border p-4 ${
            isDayMode
              ? 'border-gray-200 bg-gray-50'
              : 'border-gray-800 bg-gray-900/50'
          }`}>
            <div className="flex items-start gap-3">
              <Shield size={18} className={isDayMode ? 'text-gray-600' : 'text-gray-400'} />
              <div>
                <h4 className={`font-semibold text-sm mb-1 ${isDayMode ? 'text-gray-900' : 'text-white'}`}>
                  All Agents
                </h4>
                <p className={`text-xs ${isDayMode ? 'text-gray-600' : 'text-gray-400'}`}>
                  Research, chat, and all operations use this org.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
