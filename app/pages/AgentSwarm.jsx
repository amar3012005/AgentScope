import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  Filter,
  Folder,
  Globe2,
  Loader2,
  MapPin,
  Network,
  Play,
  RefreshCcw,
  Search,
  Sparkles,
  Square,
  Target,
} from 'lucide-react';
import apiClient from '../shared/api-client';

const fadeUp = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' } },
};

const scopeOptions = [
  {
    value: 'project',
    label: 'Project',
    icon: Folder,
    hint: 'Focus the run on a single project.',
  },
  {
    value: 'region',
    label: 'Region',
    icon: MapPin,
    hint: 'Target a graph or memory region.',
  },
  {
    value: 'graph',
    label: 'Graph',
    icon: Network,
    hint: 'Sweep a connected graph neighborhood.',
  },
  {
    value: 'workspace',
    label: 'Workspace',
    icon: Globe2,
    hint: 'Run across the broad resident surface.',
  },
];

const terminalStatuses = new Set(['completed', 'complete', 'succeeded', 'success', 'failed', 'cancelled', 'canceled', 'error', 'done', 'finished', 'stopped']);

function unwrapList(payload, keys = ['agents', 'runs', 'observations', 'items', 'data', 'results']) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== 'object') return [];
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

function normalizeAgent(agent) {
  if (!agent || typeof agent !== 'object') return null;
  return {
    ...agent,
    id: agent.id || agent.agent_id || agent.agentId || agent.slug,
    name: agent.name || agent.title || agent.label || 'Resident Agent',
    role: agent.role || agent.kind || agent.type || 'resident',
    status: agent.status || agent.state || 'idle',
    summary: agent.summary || agent.description || agent.goal || '',
    lastRunAt: agent.last_run_at || agent.lastRunAt || agent.updated_at || agent.updatedAt || null,
  };
}

function normalizeRun(run) {
  if (!run || typeof run !== 'object') return null;
  const rawProgress =
    run.progress ??
    run.progress_percent ??
    run.progressPercent ??
    run.completion_percent ??
    run.completionPercent ??
    run.percent ??
    run.pct ??
    0;
  const progress = Number.isFinite(Number(rawProgress)) ? Number(rawProgress) : 0;
  return {
    ...run,
    id: run.id || run.run_id || run.runId,
    status: run.status || run.state || run.phase || 'pending',
    progress: Math.max(0, Math.min(100, progress)),
    startedAt: run.started_at || run.startedAt || run.created_at || run.createdAt || null,
    updatedAt: run.updated_at || run.updatedAt || null,
    goal: run.goal || run.request?.goal || '',
    scope: run.scope || run.request?.scope || '',
    project: run.project || run.request?.project || '',
    region: run.region || run.request?.region || '',
    dryRun: Boolean(run.dry_run ?? run.dryRun),
    summary: run.summary || run.message || run.note || '',
    error: run.error || run.failure || null,
    trailMark: run.trail_mark || run.trailMark || run.result?.trail_mark || null,
    semanticClusters: run.result?.semantic_clusters || run.semantic_clusters || [],
    semanticProbes: run.result?.semantic_probes || run.semantic_probes || [],
  };
}

function normalizeObservation(observation) {
  if (!observation || typeof observation !== 'object') return null;
  return {
    ...observation,
    id: observation.id || observation.observation_id || observation.observationId,
    kind: observation.kind || observation.type || 'observation',
    certainty: observation.certainty ?? observation.confidence ?? observation.score ?? null,
    content: observation.content ?? observation.text ?? observation.body ?? observation.message ?? observation,
    timestamp: observation.timestamp || observation.created_at || observation.createdAt || observation.updated_at || observation.updatedAt || null,
  };
}

function isFindingObservation(observation) {
  const kind = String(observation?.kind || '').toLowerCase();
  return /(anomaly|candidate|conflict|risk|smell|hypothesis|finding|alert)/.test(kind);
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value, null, 2);
}

function normalizeStatus(status) {
  const normalized = String(status || '').toLowerCase();
  return normalized || 'idle';
}

function displayStatus(status) {
  const normalized = normalizeStatus(status);
  if (terminalStatuses.has(normalized)) return 'done';
  return normalized;
}

function statusTone(status) {
  const normalized = normalizeStatus(status);
  if (['completed', 'complete', 'succeeded', 'success', 'done', 'finished'].includes(normalized)) {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  }
  if (['running', 'in_progress', 'processing', 'queued', 'pending'].includes(normalized)) {
    return 'bg-[#117dff]/10 text-[#117dff] border-[#117dff]/20';
  }
  if (['failed', 'error'].includes(normalized)) {
    return 'bg-red-50 text-red-700 border-red-200';
  }
  if (['cancelled', 'canceled', 'stopped'].includes(normalized)) {
    return 'bg-amber-50 text-amber-700 border-amber-200';
  }
  return 'bg-[#f3f1ec] text-[#525252] border-[#e3e0db]';
}

function certaintyTone(value) {
  const certainty = Number(value);
  if (!Number.isFinite(certainty)) return 'text-[#a3a3a3]';
  if (certainty >= 0.8) return 'text-emerald-600';
  if (certainty >= 0.5) return 'text-[#117dff]';
  return 'text-amber-600';
}

function ObservationCard({ observation, accent = false }) {
  const content = formatValue(observation?.content);
  const body = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  return (
    <div className={`rounded-xl border p-4 ${accent ? 'border-[#117dff]/20 bg-[#117dff]/[0.03]' : 'border-[#e3e0db] bg-white'}`}>
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] uppercase tracking-[0.08em] font-semibold px-2 py-1 rounded-full bg-[#f3f1ec] text-[#525252]">
            {observation?.kind || 'observation'}
          </span>
          {observation?.certainty !== null && observation?.certainty !== undefined && (
            <span className={`text-[11px] font-medium ${certaintyTone(observation.certainty)}`}>
              {typeof observation.certainty === 'number' ? `${Math.round(observation.certainty * 100)}% certainty` : observation.certainty}
            </span>
          )}
        </div>
        <span className="text-[11px] text-[#a3a3a3] font-mono whitespace-nowrap">{formatDate(observation?.timestamp)}</span>
      </div>
      <p className="text-[#0a0a0a] text-[13px] leading-relaxed whitespace-pre-wrap break-words">{body}</p>
    </div>
  );
}

function Metric({ label, value, tone = 'text-[#0a0a0a]' }) {
  return (
    <div className="rounded-xl border border-[#e3e0db] bg-white px-4 py-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="text-[10px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-1">{label}</div>
      <div className={`text-sm font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function TrailMarkCard({ trailMark }) {
  if (!trailMark) return null;

  const probes = Array.isArray(trailMark.semantic_probes) ? trailMark.semantic_probes : [];
  const clusters = Array.isArray(trailMark.semantic_clusters) ? trailMark.semantic_clusters : [];
  const topCluster = clusters[0] || null;

  return (
    <div className="rounded-xl border border-[#117dff]/20 bg-[#117dff]/[0.04] p-4">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={15} className="text-[#117dff]" />
        <h3 className="text-sm font-semibold text-[#0a0a0a]">Semantic trail mark</h3>
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-1">Label</div>
          <div className="text-[#0a0a0a] font-medium">{trailMark.label || '—'}</div>
        </div>

        <div>
          <div className="text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-1">Next agent</div>
          <div className="text-[#525252] leading-relaxed whitespace-pre-wrap">
            {trailMark.next_agent_prompt || trailMark.summary || '—'}
          </div>
        </div>

        {topCluster ? (
          <div>
            <div className="text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-1">Top cluster</div>
            <div className="text-[#0a0a0a]">{topCluster.label}</div>
            <div className="text-xs text-[#525252] mt-1">
              {topCluster.count} memories
              {topCluster.keywords?.length ? ` · ${topCluster.keywords.slice(0, 5).join(', ')}` : ''}
            </div>
          </div>
        ) : null}

        {probes.length ? (
          <div>
            <div className="text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-2">Semantic probes</div>
            <div className="flex flex-wrap gap-2">
              {probes.slice(0, 8).map((probe) => (
                <span
                  key={probe}
                  className="inline-flex items-center rounded-full border border-[#117dff]/15 bg-white px-2.5 py-1 text-[11px] text-[#0a0a0a]"
                >
                  {probe}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function AgentSwarm() {
  const [agents, setAgents] = useState([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [scope, setScope] = useState('project');
  const [project, setProject] = useState('');
  const [region, setRegion] = useState('');
  const [goal, setGoal] = useState('Sweep the current scope for anomalies, stale assumptions, and high-risk signals.');
  const [dryRun, setDryRun] = useState(true);
  const [currentRunId, setCurrentRunId] = useState('');
  const [currentRun, setCurrentRun] = useState(null);
  const [observations, setObservations] = useState([]);
  const [runMessage, setRunMessage] = useState('');
  const [runError, setRunError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || agents[0] || null,
    [agents, selectedAgentId],
  );

  const sortedObservations = useMemo(
    () =>
      [...observations].sort((a, b) => {
        const aTime = new Date(a.timestamp || 0).getTime();
        const bTime = new Date(b.timestamp || 0).getTime();
        return bTime - aTime;
      }),
    [observations],
  );

  const findings = useMemo(() => sortedObservations.filter(isFindingObservation), [sortedObservations]);
  const regularObservations = useMemo(
    () => sortedObservations.filter((observation) => !isFindingObservation(observation)),
    [sortedObservations],
  );

  const currentStatus = displayStatus(currentRun?.status || (busy ? 'starting' : 'idle'));
  const progress = currentRun?.progress ?? (currentStatus === 'running' ? 50 : 0);

  const loadAgents = useCallback(async () => {
    setAgentsLoading(true);
    setAgentsError('');
    try {
      const response = await apiClient.listResidentAgents();
      const list = unwrapList(response).map(normalizeAgent).filter(Boolean);
      setAgents(list);
      setSelectedAgentId((current) => {
        if (current) return current;
        const faraday = list.find((agent) => /faraday/i.test(`${agent.name} ${agent.role} ${agent.summary}`));
        return (faraday || list[0] || {}).id || '';
      });
    } catch (error) {
      setAgentsError(error.response?.data?.error || error.message || 'Failed to load resident agents.');
    } finally {
      setAgentsLoading(false);
    }
  }, []);

  const loadRunState = async (runId) => {
    if (!runId) return;
    try {
      const [runResponse, observationResponse] = await Promise.all([
        apiClient.getResidentRun(runId),
        apiClient.listResidentRunObservations(runId),
      ]);
      const normalizedRun = normalizeRun(runResponse?.run || runResponse);
      const normalizedObservations = unwrapList(observationResponse).map(normalizeObservation).filter(Boolean);
      setCurrentRun(normalizedRun);
      setObservations(normalizedObservations);
      setRunMessage(normalizedRun?.summary || '');
      if (normalizedRun?.error) {
        setRunError(formatValue(normalizedRun.error));
      }
      return { run: normalizedRun, observations: normalizedObservations };
    } catch (error) {
      setRunError(error.response?.data?.error || error.message || 'Failed to refresh run state.');
      return null;
    }
  };

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    if (!currentRunId) return undefined;

    let intervalId;
    let cancelled = false;

    const sync = async () => {
      const nextState = await loadRunState(currentRunId);
      if (cancelled) return;
      if (nextState?.run) {
        const nextStatus = normalizeStatus(nextState.run.status);
        if (terminalStatuses.has(nextStatus)) {
          setBusy(false);
          if (intervalId) clearInterval(intervalId);
        }
      }
    };

    sync();
    intervalId = window.setInterval(sync, 2500);

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRunId]);

  const handleStartRun = async () => {
    const agentId = selectedAgent?.id;
    if (!agentId) {
      setRunError('No resident agent is available to run.');
      return;
    }

    setBusy(true);
    setRunError('');
    setRunMessage('');

    const payload = {
      scope,
      goal: goal.trim() || undefined,
      project: project.trim() || undefined,
      region: region.trim() || undefined,
      dry_run: dryRun,
    };

    try {
      const response = await apiClient.runResidentAgent(agentId, payload);
      const runId = response?.run_id || response?.runId || response?.id || response?.run?.id;
      const nextRun = normalizeRun(response?.run || response);
      if (runId) setCurrentRunId(runId);
      if (nextRun) setCurrentRun(nextRun);
      if (Array.isArray(response?.observations)) {
        setObservations(response.observations.map(normalizeObservation).filter(Boolean));
      }
      setRunMessage(response?.message || response?.summary || 'Resident agent run started.');
    } catch (error) {
      setRunError(error.response?.data?.error || error.message || 'Failed to start resident agent run.');
      setBusy(false);
    }
  };

  const handleRefresh = async () => {
    if (!currentRunId) return;
    setRefreshing(true);
    try {
      await loadRunState(currentRunId);
    } finally {
      setRefreshing(false);
    }
  };

  const handleCancel = async () => {
    if (!currentRunId) return;
    setBusy(false);
    try {
      const response = await apiClient.cancelResidentRun(currentRunId);
      const nextRun = normalizeRun(response?.run || response);
      if (nextRun) setCurrentRun(nextRun);
      await loadRunState(currentRunId);
    } catch (error) {
      setRunError(error.response?.data?.error || error.message || 'Failed to cancel the run.');
    }
  };

  return (
    <div className="min-h-full">
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[#117dff]/20 to-[#8b5cf6]/20 border border-[#117dff]/20 flex items-center justify-center flex-shrink-0">
              <Bot size={24} className="text-[#117dff]" />
            </div>
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#117dff]/10 border border-[#117dff]/20 mb-3">
                <Sparkles size={12} className="text-[#117dff]" />
                <span className="text-[#117dff] text-[11px] font-semibold uppercase tracking-wider">
                  Resident agents
                </span>
              </div>
              <h1 className="text-[#0a0a0a] text-2xl font-bold font-['Space_Grotesk']">Faraday Console</h1>
              <p className="text-[#525252] text-sm font-['Space_Grotesk'] max-w-2xl leading-relaxed">
                Run resident graph-native agents, inspect live progress, and review the observations they emit
                while they sweep your scope for anomalies, stale assumptions, and risk signals.
              </p>
            </div>
          </div>

          <div className="inline-flex items-center gap-2 rounded-full border border-[#e3e0db] bg-white px-3 py-2 text-xs text-[#525252] shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <Activity size={14} className="text-[#117dff]" />
            <span>Live resident run console</span>
          </div>
        </div>
      </motion.div>

      <motion.div
        variants={fadeUp}
        initial="hidden"
        animate="visible"
        className="grid gap-3 md:grid-cols-2 xl:grid-cols-4 mb-6"
      >
        <Metric label="Agents" value={agentsLoading ? 'Loading…' : String(agents.length)} tone="text-[#0a0a0a]" />
        <Metric label="Selected agent" value={selectedAgent?.name || 'Faraday'} tone="text-[#0a0a0a]" />
        <Metric label="Run status" value={currentStatus} tone="text-[#117dff]" />
        <Metric label="Observations" value={String(sortedObservations.length)} tone="text-[#0a0a0a]" />
      </motion.div>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-6">
          <motion.section variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="text-[#0a0a0a] text-base font-bold font-['Space_Grotesk']">Resident agents</h2>
                <p className="text-[#a3a3a3] text-xs">Select the agent to run and inspect.</p>
              </div>
              <button
                type="button"
                onClick={loadAgents}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#e3e0db] px-2.5 py-1.5 text-xs text-[#525252] hover:border-[#117dff]/20 hover:text-[#0a0a0a] transition-colors"
              >
                <RefreshCcw size={13} className={agentsLoading ? 'animate-spin' : ''} />
                Refresh
              </button>
            </div>

            {agentsError ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {agentsError}
              </div>
            ) : null}

            <div className="space-y-3">
              {agentsLoading && !agents.length ? (
                <div className="space-y-2">
                  {[0, 1, 2].map((index) => (
                    <div key={index} className="animate-pulse rounded-xl border border-[#e3e0db] bg-[#faf9f4] p-4">
                      <div className="h-4 w-24 rounded bg-[#e3e0db] mb-3" />
                      <div className="h-3 w-full rounded bg-[#eeeae3] mb-2" />
                      <div className="h-3 w-2/3 rounded bg-[#eeeae3]" />
                    </div>
                  ))}
                </div>
              ) : null}

              {!agentsLoading && !agents.length && !agentsError ? (
                <div className="rounded-xl border border-dashed border-[#e3e0db] bg-[#faf9f4] px-4 py-5 text-sm text-[#525252]">
                  No resident agents were returned yet. Once the backend exposes them, Faraday will appear here.
                </div>
              ) : null}

              {agents.map((agent) => {
                const active = agent.id === selectedAgent?.id;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => setSelectedAgentId(agent.id)}
                    className={`w-full text-left rounded-xl border p-4 transition-all ${
                      active
                        ? 'border-[#117dff]/25 bg-[#117dff]/[0.04] shadow-[0_4px_12px_rgba(17,125,255,0.08)]'
                        : 'border-[#e3e0db] bg-white hover:border-[#117dff]/20 hover:bg-[#faf9f4]'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-[#0a0a0a] font-['Space_Grotesk'] truncate">
                            {agent.name}
                          </span>
                          {active ? (
                            <span className="text-[10px] uppercase tracking-[0.08em] px-2 py-0.5 rounded-full bg-[#117dff] text-white">
                              Selected
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-[#525252]">
                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 ${statusTone(agent.status)}`}>
                              {displayStatus(agent.status)}
                            </span>
                          <span className="truncate">{agent.role}</span>
                        </div>
                      </div>
                      <ChevronRight size={15} className={active ? 'text-[#117dff]' : 'text-[#c4c4c4]'} />
                    </div>
                    <p className="text-xs text-[#525252] leading-relaxed line-clamp-3">{agent.summary || 'No description available.'}</p>
                    {agent.lastRunAt ? (
                      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-[#a3a3a3]">
                        <Clock3 size={12} />
                        Last run {formatDate(agent.lastRunAt)}
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </motion.section>

          <motion.section variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex items-center gap-2 mb-4">
              <Target size={16} className="text-[#117dff]" />
              <h2 className="text-[#0a0a0a] text-base font-bold font-['Space_Grotesk']">Faraday run form</h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-2">
                  Scope
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {scopeOptions.map((option) => {
                    const active = scope === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setScope(option.value)}
                        className={`rounded-xl border p-3 text-left transition-all ${
                          active
                            ? 'border-[#117dff]/25 bg-[#117dff]/[0.05]'
                            : 'border-[#e3e0db] bg-white hover:border-[#117dff]/20 hover:bg-[#faf9f4]'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <option.icon size={15} className={active ? 'text-[#117dff]' : 'text-[#a3a3a3]'} />
                            <span className="text-sm font-semibold text-[#0a0a0a]">{option.label}</span>
                          </div>
                          {active ? <CheckCircle2 size={14} className="text-[#117dff]" /> : null}
                        </div>
                        <p className="text-[11px] text-[#525252] leading-relaxed">{option.hint}</p>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-2">
                    Project
                  </span>
                  <input
                    value={project}
                    onChange={(event) => setProject(event.target.value)}
                    placeholder="bench/longmemeval or a product project"
                    className="w-full rounded-xl border border-[#e3e0db] bg-white px-3 py-2.5 text-sm text-[#0a0a0a] outline-none transition-colors placeholder:text-[#c4c4c4] focus:border-[#117dff]/30 focus:ring-2 focus:ring-[#117dff]/10"
                  />
                </label>

                <label className="block">
                  <span className="block text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-2">
                    Region
                  </span>
                  <input
                    value={region}
                    onChange={(event) => setRegion(event.target.value)}
                    placeholder="graph region, file path, or memory region"
                    className="w-full rounded-xl border border-[#e3e0db] bg-white px-3 py-2.5 text-sm text-[#0a0a0a] outline-none transition-colors placeholder:text-[#c4c4c4] focus:border-[#117dff]/30 focus:ring-2 focus:ring-[#117dff]/10"
                  />
                </label>
              </div>

              <label className="block">
                <span className="block text-[11px] uppercase tracking-[0.08em] text-[#a3a3a3] font-semibold mb-2">
                  Goal
                </span>
                <textarea
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                  rows={4}
                  placeholder="Describe what Faraday should look for."
                  className="w-full rounded-xl border border-[#e3e0db] bg-white px-3 py-2.5 text-sm text-[#0a0a0a] outline-none transition-colors placeholder:text-[#c4c4c4] focus:border-[#117dff]/30 focus:ring-2 focus:ring-[#117dff]/10 resize-none"
                />
              </label>

              <label className="flex items-center gap-3 rounded-xl border border-[#e3e0db] bg-[#faf9f4] px-3 py-2.5">
                <input
                  type="checkbox"
                  checked={dryRun}
                  onChange={(event) => setDryRun(event.target.checked)}
                  className="h-4 w-4 rounded border-[#c4c4c4] text-[#117dff] focus:ring-[#117dff]"
                />
                <div>
                  <div className="text-sm font-medium text-[#0a0a0a]">Dry run</div>
                  <div className="text-[11px] text-[#525252]">Preview the run without persisting changes if the backend supports it.</div>
                </div>
              </label>

              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  type="button"
                  onClick={handleStartRun}
                  disabled={!selectedAgent || busy}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#117dff] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_4px_16px_rgba(17,125,255,0.18)] transition-colors hover:bg-[#0f6fe0] disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                  Run Faraday
                </button>
                <button
                  type="button"
                  onClick={handleCancel}
                  disabled={!currentRunId}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#e3e0db] bg-white px-4 py-2.5 text-sm font-semibold text-[#525252] transition-colors hover:border-[#dc2626]/20 hover:text-[#dc2626] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Square size={15} />
                  Cancel run
                </button>
              </div>

              {runError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
                  <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                  <span>{runError}</span>
                </div>
              ) : null}
              {runMessage ? (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 flex items-start gap-2">
                  <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0" />
                  <span>{runMessage}</span>
                </div>
              ) : null}
            </div>
          </motion.section>
        </div>

        <div className="space-y-6">
          <motion.section variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Clock3 size={16} className="text-[#117dff]" />
                  <h2 className="text-[#0a0a0a] text-base font-bold font-['Space_Grotesk']">Live run status</h2>
                </div>
                <p className="text-sm text-[#525252] max-w-2xl">
                  {currentRunId
                    ? `Run ${currentRunId} is being tracked live. The panel refreshes automatically while the agent is active.`
                    : 'Start a run to see status, progress, and emitted observations here.'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={!currentRunId || refreshing}
                  className="inline-flex items-center gap-2 rounded-xl border border-[#e3e0db] bg-white px-3 py-2 text-sm font-semibold text-[#525252] transition-colors hover:border-[#117dff]/20 hover:text-[#0a0a0a] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RefreshCcw size={15} className={refreshing ? 'animate-spin' : ''} />
                  Refresh
                </button>
                <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.08em] ${statusTone(currentStatus)}`}>
                  {currentStatus}
                </span>
              </div>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <Metric label="Progress" value={`${Math.round(progress)}%`} tone="text-[#0a0a0a]" />
              <Metric label="Scope" value={scope} tone="text-[#0a0a0a]" />
              <Metric label="Mode" value={dryRun ? 'Dry run' : 'Execute'} tone="text-[#0a0a0a]" />
            </div>

            <div className="mt-5">
              <div className="flex items-center justify-between text-xs text-[#a3a3a3] mb-2">
                <span>Progress</span>
                <span>{currentRunId ? `Run ${currentRunId}` : 'Idle'}</span>
              </div>
              <div className="h-2 rounded-full bg-[#f3f1ec] overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-[#117dff] to-[#8b5cf6] transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
                />
              </div>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-[#e3e0db] bg-[#faf9f4] p-4">
                <div className="flex items-center gap-2 mb-3">
                  <FileText size={15} className="text-[#117dff]" />
                  <h3 className="text-sm font-semibold text-[#0a0a0a]">Run details</h3>
                </div>
                <dl className="space-y-2 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <dt className="text-[#a3a3a3]">Agent</dt>
                    <dd className="text-[#0a0a0a] text-right">{selectedAgent?.name || '—'}</dd>
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <dt className="text-[#a3a3a3]">Goal</dt>
                    <dd className="text-[#0a0a0a] text-right max-w-[60%]">{goal || '—'}</dd>
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <dt className="text-[#a3a3a3]">Project</dt>
                    <dd className="text-[#0a0a0a] text-right">{project || '—'}</dd>
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <dt className="text-[#a3a3a3]">Region</dt>
                    <dd className="text-[#0a0a0a] text-right">{region || '—'}</dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-xl border border-[#e3e0db] bg-[#faf9f4] p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles size={15} className="text-[#117dff]" />
                  <h3 className="text-sm font-semibold text-[#0a0a0a]">Live summary</h3>
                </div>
                <p className="text-sm text-[#525252] leading-relaxed whitespace-pre-wrap">
                  {currentRun?.summary || runMessage || (currentRunId ? 'Waiting for the agent to emit progress.' : 'No run active yet.')}
                </p>
                {currentRun?.error ? (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {formatValue(currentRun.error)}
                  </div>
                ) : null}
              </div>
            </div>

            {currentRun?.trailMark ? (
              <div className="mt-5">
                <TrailMarkCard trailMark={currentRun.trailMark} />
              </div>
            ) : null}
          </motion.section>

          <div className="grid gap-6 xl:grid-cols-2">
            <motion.section variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <Search size={16} className="text-[#117dff]" />
                    <h2 className="text-[#0a0a0a] text-base font-bold font-['Space_Grotesk']">Observation feed</h2>
                  </div>
                  <p className="text-xs text-[#a3a3a3] mt-1">Structured observations emitted by the resident agent.</p>
                </div>
                <span className="text-xs text-[#525252] px-2.5 py-1 rounded-full bg-[#f3f1ec]">{regularObservations.length}</span>
              </div>

              <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
                {regularObservations.length ? (
                  regularObservations.map((observation, index) => (
                    <ObservationCard key={observation.id || `${observation.kind}-${index}`} observation={observation} />
                  ))
                ) : (
                  <div className="rounded-xl border border-dashed border-[#e3e0db] bg-[#faf9f4] px-4 py-8 text-center text-sm text-[#525252]">
                    Observations will appear here while Faraday is running.
                  </div>
                )}
              </div>
            </motion.section>

            <motion.section variants={fadeUp} initial="hidden" animate="visible" className="bg-white border border-[#e3e0db] rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <Filter size={16} className="text-[#117dff]" />
                    <h2 className="text-[#0a0a0a] text-base font-bold font-['Space_Grotesk']">Findings feed</h2>
                  </div>
                  <p className="text-xs text-[#a3a3a3] mt-1">Higher-signal anomaly, risk, and hypothesis candidates.</p>
                </div>
                <span className="text-xs text-[#525252] px-2.5 py-1 rounded-full bg-[#f3f1ec]">{findings.length}</span>
              </div>

              <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
                {findings.length ? (
                  findings.map((observation, index) => (
                    <ObservationCard key={observation.id || `${observation.kind}-${index}`} observation={observation} accent />
                  ))
                ) : (
                  <div className="rounded-xl border border-dashed border-[#e3e0db] bg-[#faf9f4] px-4 py-8 text-center text-sm text-[#525252]">
                    Candidate findings will appear here when Faraday detects a meaningful signal.
                  </div>
                )}
              </div>
            </motion.section>
          </div>
        </div>
      </div>
    </div>
  );
}
