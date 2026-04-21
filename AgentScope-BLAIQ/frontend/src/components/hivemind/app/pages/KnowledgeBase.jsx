import React, { useState, useEffect } from 'react';
import { ShieldCheck, Key, User, Building, Save, CheckCircle2, AlertCircle } from 'lucide-react';
import '../shared/bmw-reference-theme.css';

export default function KnowledgeBase() {
  const [orgName, setOrgName] = useState('');
  const [activeRun, setActiveRun] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);
  
  // Credentials state
  const [creds, setCreds] = useState({
    api_key: 'hmk_live_77cb382f41508088498a79de13c836fa99f137c543a5f97e',
    user_id: 'e8df9371-632c-442f-b6c7-6c6218b5b4d2',
    org_id: '9254abfe-8aae-4d51-8677-533236727b46',
    base_url: 'https://core.hivemind.davinciai.eu:8050'
  });

  const [stats, setStats] = useState({
    memoryFindings: 0,
    webFindings: 0,
    uploadFindings: 0,
    saveBack: 'Manual only',
  });

  useEffect(() => {
    // Fetch HiveMind org info from backend
    const fetchHiveMindInfo = async () => {
      try {
        const response = await fetch('/api/v1/hivemind/org-info', {
          headers: { Accept: 'application/json' },
        });
        if (response.ok) {
          const data = await response.json();
          setOrgName(data.org_name || 'HiveMind Org');
          setStats({
            memoryFindings: data.memory_findings || 0,
            webFindings: data.web_findings || 0,
            uploadFindings: data.upload_findings || 0,
            saveBack: data.save_back || 'Manual only',
          });
          
          // If the backend is already configured, we might want to update our local state
          // but for this request, the user provided specific values to set.
        }
      } catch (error) {
        console.error('Failed to fetch HiveMind org info:', error);
      }
    };

    fetchHiveMindInfo();
  }, []);

  const handleUpdateCredentials = async (e) => {
    e.preventDefault();
    setLoading(true);
    setSaveStatus(null);
    try {
      const response = await fetch('/api/v1/hivemind/credentials/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(creds),
      });
      
      if (response.ok) {
        setSaveStatus('success');
        setOrgName(creds.org_id);
      } else {
        setSaveStatus('error');
      }
    } catch (error) {
      console.error('Failed to save credentials:', error);
      setSaveStatus('error');
    } finally {
      setLoading(false);
      setTimeout(() => setSaveStatus(null), 3000);
    }
  };

  return (
    <div className="h-full flex flex-col p-8 bg-black text-white overflow-y-auto">
      {/* Header with status badge */}
      <div className="flex items-start justify-between mb-12">
        <div>
          <h1 className="text-4xl font-light tracking-tight mb-3 uppercase">
            HiveMind Enterprise<br />Control Plane
          </h1>
          <p className="text-sm text-gray-400 max-w-2xl font-mono uppercase tracking-wider">
            Configure dynamic agent credentials for automated memory and research workflows.
          </p>
        </div>
        <div className="rounded-none bg-[#111] px-4 py-2 border border-gray-800">
          <div className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.2em]">
            {activeRun ? 'Status: Active' : 'Status: Ready'}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left column: Credentials Form */}
        <div className="lg:col-span-2">
          <div className="bmw-card p-8 border-t-2 border-t-[#222]">
            <div className="flex items-center gap-3 mb-8">
              <ShieldCheck className="text-gray-400" size={20} />
              <h2 className="text-lg font-light uppercase tracking-widest">Enterprise Credentials</h2>
            </div>
            
            <form onSubmit={handleUpdateCredentials} className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-[10px] uppercase tracking-widest text-gray-500 mb-2 font-bold">API Key</label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" size={14} />
                    <input 
                      type="password"
                      value={creds.api_key}
                      onChange={(e) => setCreds({...creds, api_key: e.target.value})}
                      className="w-full bg-black border border-gray-800 rounded-none px-10 py-3 text-sm font-mono focus:border-white transition-colors outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[10px] uppercase tracking-widest text-gray-500 mb-2 font-bold">Base URL</label>
                  <input 
                    type="text"
                    value={creds.base_url}
                    onChange={(e) => setCreds({...creds, base_url: e.target.value})}
                    className="w-full bg-black border border-gray-800 rounded-none px-4 py-3 text-sm font-mono focus:border-white transition-colors outline-none"
                  />
                </div>

                <div>
                  <label className="block text-[10px] uppercase tracking-widest text-gray-500 mb-2 font-bold">User ID</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" size={14} />
                    <input 
                      type="text"
                      value={creds.user_id}
                      onChange={(e) => setCreds({...creds, user_id: e.target.value})}
                      className="w-full bg-black border border-gray-800 rounded-none px-10 py-3 text-sm font-mono focus:border-white transition-colors outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[10px] uppercase tracking-widest text-gray-500 mb-2 font-bold">Organization ID</label>
                  <div className="relative">
                    <Building className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" size={14} />
                    <input 
                      type="text"
                      value={creds.org_id}
                      onChange={(e) => setCreds({...creds, org_id: e.target.value})}
                      className="w-full bg-black border border-gray-800 rounded-none px-10 py-3 text-sm font-mono focus:border-white transition-colors outline-none"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between pt-4">
                <p className="text-[11px] text-gray-500 max-w-md italic">
                  Changes applied here will update all running agents dynamically. No restart required.
                </p>
                <button 
                  type="submit"
                  disabled={loading}
                  className="flex items-center gap-2 bg-white text-black px-8 py-3 text-xs font-bold uppercase tracking-widest hover:bg-gray-200 transition-colors disabled:opacity-50"
                >
                  {loading ? 'Processing...' : (
                    <>
                      <Save size={14} />
                      Save Configuration
                    </>
                  )}
                </button>
              </div>

              {saveStatus === 'success' && (
                <div className="mt-4 flex items-center gap-2 text-green-500 text-xs font-bold uppercase tracking-widest animate-pulse">
                  <CheckCircle2 size={14} />
                  Credentials updated successfully
                </div>
              )}
              {saveStatus === 'error' && (
                <div className="mt-4 flex items-center gap-2 text-red-500 text-xs font-bold uppercase tracking-widest animate-pulse">
                  <AlertCircle size={14} />
                  Failed to update credentials
                </div>
              )}
            </form>
          </div>
        </div>

        {/* Right column: Current Status */}
        <div>
          <div className="bmw-card p-6 mb-6">
            <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">
              Active Environment
            </div>
            <div className="space-y-4">
              <div>
                <div className="text-[10px] text-gray-600 uppercase mb-1">Organization</div>
                <div className="text-lg font-light tracking-tight truncate">
                  {orgName || 'Disconnected'}
                </div>
              </div>
              <div className="pt-4 border-t border-gray-900">
                <div className="text-[10px] text-gray-600 uppercase mb-3">Sync Status</div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-[10px] text-gray-500">Memory Graph</div>
                    <div className="text-xs text-green-400 uppercase font-bold tracking-wider mt-1">Live</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500">Agent Handshake</div>
                    <div className="text-xs text-green-400 uppercase font-bold tracking-wider mt-1">Verified</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="bmw-card p-4 flex items-center justify-between">
              <div className="text-[10px] text-gray-500 uppercase font-bold">Memory Findings</div>
              <div className="text-xl font-light">{stats.memoryFindings}</div>
            </div>
            <div className="bmw-card p-4 flex items-center justify-between">
              <div className="text-[10px] text-gray-500 uppercase font-bold">Web Findings</div>
              <div className="text-xl font-light">{stats.webFindings}</div>
            </div>
            <div className="bmw-card p-4 flex items-center justify-between">
              <div className="text-[10px] text-gray-500 uppercase font-bold">Upload Findings</div>
              <div className="text-xl font-light">{stats.uploadFindings}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
