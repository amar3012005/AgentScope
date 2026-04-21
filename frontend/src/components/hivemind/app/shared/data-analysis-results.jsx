import React, { useState, useMemo } from 'react';
import { BarChart3, TrendingUp, PieChart, Activity, AlertTriangle, CheckCircle, FileText, Download } from 'lucide-react';

/**
 * DataAnalysisResults — Renders analysis results from DataScienceAgent
 *
 * Props:
 * - analysisResult: AnalysisResult from EvidencePack
 * - isDayMode: boolean for light/dark theme
 */
export function DataAnalysisResults({ analysisResult, isDayMode }) {
  const d = isDayMode;

  if (!analysisResult) {
    return null;
  }

  const {
    dataset_info = [],
    code_execution = null,
    statistical_results = [],
    visualizations = [],
    key_findings = [],
    limitations = [],
    recommendations = [],
  } = analysisResult;

  return (
    <div className={`mt-4 space-y-4 rounded-xl border p-4 ${d ? 'border-gray-200 bg-gray-50' : 'border-[#2a2a2a] bg-[#141414]'}`}>
      {/* Dataset Info */}
      {dataset_info.length > 0 && (
        <DatasetSummary schemas={dataset_info} isDayMode={d} />
      )}

      {/* Key Findings */}
      {key_findings.length > 0 && (
        <KeyFindings findings={key_findings} isDayMode={d} />
      )}

      {/* Statistical Results */}
      {statistical_results.length > 0 && (
        <StatisticalResults results={statistical_results} isDayMode={d} />
      )}

      {/* Visualizations */}
      {visualizations.length > 0 && (
        <VisualizationGallery visualizations={visualizations} isDayMode={d} />
      )}

      {/* Limitations */}
      {limitations.length > 0 && (
        <LimitationsList limitations={limitations} isDayMode={d} />
      )}

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <RecommendationsList recommendations={recommendations} isDayMode={d} />
      )}

      {/* Code Execution Info */}
      {code_execution && (
        <CodeExecutionInfo execution={code_execution} isDayMode={d} />
      )}
    </div>
  );
}

function DatasetSummary({ schemas, isDayMode }) {
  const d = isDayMode;

  return (
    <div className={`rounded-lg border p-3 ${d ? 'border-gray-200 bg-white' : 'border-[#2a2a2a] bg-[#1e1e1e]'}`}>
      <div className="mb-2 flex items-center gap-2">
        <FileText size={16} className={d ? 'text-gray-600' : 'text-[#8a8a8a]'} />
        <h3 className={`text-sm font-medium ${d ? 'text-gray-900' : 'text-white'}`}>Dataset Summary</h3>
      </div>
      <div className="space-y-2">
        {schemas.map((schema, idx) => (
          <div
            key={idx}
            className={`rounded-md border p-2 text-xs ${d ? 'border-gray-100 bg-gray-50' : 'border-[#333] bg-[#1a1a1a]'}`}
          >
            <div className={`font-medium ${d ? 'text-gray-700' : 'text-[#ccc]'}`}>
              {schema.column_name}
              <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${d ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/30 text-blue-300'}`}>
                {schema.data_type}
              </span>
            </div>
            <div className={`mt-1 ${d ? 'text-gray-500' : 'text-[#666]'}`}>
              {schema.unique_count} unique values
              {schema.statistics && (
                <span className="ml-2">
                  | Range: {schema.statistics.min?.toFixed?.(2) || schema.statistics.min} - {schema.statistics.max?.toFixed?.(2) || schema.statistics.max}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function KeyFindings({ findings, isDayMode }) {
  const d = isDayMode;

  return (
    <div className={`rounded-lg border p-3 ${d ? 'border-emerald-200 bg-emerald-50' : 'border-emerald-900/30 bg-emerald-900/10'}`}>
      <div className="mb-2 flex items-center gap-2">
        <CheckCircle size={16} className="text-emerald-500" />
        <h3 className={`text-sm font-medium ${d ? 'text-emerald-900' : 'text-emerald-200'}`}>Key Findings</h3>
      </div>
      <ul className="space-y-1.5">
        {findings.map((finding, idx) => (
          <li
            key={idx}
            className={`flex items-start gap-2 text-sm ${d ? 'text-emerald-800' : 'text-emerald-300'}`}
          >
            <span className="mt-1 flex h-1.5 w-1.5 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500" />
            <span>{finding}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatisticalResults({ results, isDayMode }) {
  const d = isDayMode;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-lg border p-3 ${d ? 'border-gray-200 bg-white' : 'border-[#2a2a2a] bg-[#1e1e1e]'}`}>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={16} className={d ? 'text-gray-600' : 'text-[#8a8a8a]'} />
          <h3 className={`text-sm font-medium ${d ? 'text-gray-900' : 'text-white'}`}>Statistical Analysis</h3>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className={`text-xs ${d ? 'text-gray-500 hover:text-gray-700' : 'text-[#666] hover:text-[#888]'}`}
        >
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>

      {expanded && (
        <div className="space-y-2">
          {results.map((result, idx) => (
            <div
              key={idx}
              className={`rounded-md border p-2 text-xs ${d ? 'border-gray-100 bg-gray-50' : 'border-[#333] bg-[#1a1a1a]'}`}
            >
              <div className={`font-medium ${d ? 'text-gray-700' : 'text-[#ccc]'}`}>{result.test_name}</div>
              <div className={`mt-1 ${d ? 'text-gray-600' : 'text-[#888]'}`}>{result.interpretation}</div>
              {result.result_dict && (
                <div className={`mt-1.5 rounded bg-black/5 p-1.5 font-mono text-[10px] ${d ? 'bg-gray-100' : 'bg-black/20'}`}>
                  {Object.entries(result.result_dict).map(([key, value]) => (
                    <span key={key} className="mr-3">
                      {key}: {typeof value === 'number' ? value.toFixed(4) : value}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function VisualizationGallery({ visualizations, isDayMode }) {
  const d = isDayMode;

  return (
    <div className={`rounded-lg border p-3 ${d ? 'border-gray-200 bg-white' : 'border-[#2a2a2a] bg-[#1e1e1e]'}`}>
      <div className="mb-3 flex items-center gap-2">
        <BarChart3 size={16} className={d ? 'text-gray-600' : 'text-[#8a8a8a]'} />
        <h3 className={`text-sm font-medium ${d ? 'text-gray-900' : 'text-white'}`}>Visualizations</h3>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {visualizations.map((viz) => (
          <div
            key={viz.viz_id}
            className={`overflow-hidden rounded-lg border ${d ? 'border-gray-200' : 'border-[#333]'}`}
          >
            <div className={`border-b px-3 py-2 text-xs font-medium ${d ? 'border-gray-100 bg-gray-50 text-gray-700' : 'border-[#333] bg-[#1a1a1a] text-[#ccc]'}`}>
              {viz.title}
            </div>
            <div className="p-3">
              {viz.plotly_json ? (
                <PlotlyRenderer plotlyJson={viz.plotly_json} />
              ) : (
                <div className={`flex h-32 items-center justify-center text-xs ${d ? 'text-gray-400' : 'text-[#666]'}`}>
                  {viz.viz_type} visualization
                </div>
              )}
            </div>
            <div className={`border-t px-3 py-2 text-[10px] ${d ? 'border-gray-100 bg-gray-50 text-gray-500' : 'border-[#333] bg-[#1a1a1a] text-[#666]'}`}>
              {viz.description}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlotlyRenderer({ plotlyJson }) {
  // Placeholder for actual Plotly rendering
  // In production: use react-plotly.js or plotly.js
  return (
    <div className="h-48 bg-gradient-to-br from-blue-500/10 to-purple-500/10 flex items-center justify-center rounded">
      <span className="text-xs text-gray-400">Interactive chart (Plotly)</span>
    </div>
  );
}

function LimitationsList({ limitations, isDayMode }) {
  const d = isDayMode;

  return (
    <div className={`rounded-lg border border-amber-200 bg-amber-50 p-3 ${d ? 'border-amber-200 bg-amber-50' : 'border-amber-900/30 bg-amber-900/10'}`}>
      <div className="mb-2 flex items-center gap-2">
        <AlertTriangle size={16} className="text-amber-500" />
        <h3 className={`text-sm font-medium ${d ? 'text-amber-900' : 'text-amber-200'}`}>Limitations</h3>
      </div>
      <ul className="space-y-1.5">
        {limitations.map((limitation, idx) => (
          <li
            key={idx}
            className={`flex items-start gap-2 text-sm ${d ? 'text-amber-800' : 'text-amber-300'}`}
          >
            <span className="mt-1 flex h-1.5 w-1.5 flex-shrink-0 items-center justify-center rounded-full bg-amber-500" />
            <span>{limitation}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecommendationsList({ recommendations, isDayMode }) {
  const d = isDayMode;

  return (
    <div className={`rounded-lg border border-blue-200 bg-blue-50 p-3 ${d ? 'border-blue-200 bg-blue-50' : 'border-blue-900/30 bg-blue-900/10'}`}>
      <div className="mb-2 flex items-center gap-2">
        <TrendingUp size={16} className="text-blue-500" />
        <h3 className={`text-sm font-medium ${d ? 'text-blue-900' : 'text-blue-200'}`}>Recommendations</h3>
      </div>
      <ul className="space-y-1.5">
        {recommendations.map((rec, idx) => (
          <li
            key={idx}
            className={`flex items-start gap-2 text-sm ${d ? 'text-blue-800' : 'text-blue-300'}`}
          >
            <span className="mt-1 flex h-1.5 w-1.5 flex-shrink-0 items-center justify-center rounded-full bg-blue-500" />
            <span>{rec}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CodeExecutionInfo({ execution, isDayMode }) {
  const d = isDayMode;
  const [showCode, setShowCode] = useState(false);
  const [showOutput, setShowOutput] = useState(false);

  const success = execution.exit_code === 0;

  return (
    <div className={`rounded-lg border p-3 ${d ? 'border-gray-200 bg-white' : 'border-[#2a2a2a] bg-[#1e1e1e]'}`}>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-medium ${success ? 'bg-emerald-500 text-white' : 'bg-red-500 text-white'}`}>
            {success ? '✓' : '✗'}
          </div>
          <h3 className={`text-sm font-medium ${d ? 'text-gray-900' : 'text-white'}`}>
            Code Execution
          </h3>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className={d ? 'text-gray-500' : 'text-[#666]'}>
            {execution.execution_time_ms}ms
          </span>
          <button
            onClick={() => setShowCode(!showCode)}
            className={d ? 'text-gray-500 hover:text-gray-700' : 'text-[#666] hover:text-[#888]'}
          >
            {showCode ? 'Hide Code' : 'View Code'}
          </button>
        </div>
      </div>

      {showCode && (
        <pre className={`max-h-64 overflow-auto rounded border p-2 text-[10px] font-mono ${d ? 'border-gray-200 bg-gray-50 text-gray-800' : 'border-[#333] bg-[#0a0a0a] text-gray-300'}`}>
          {execution.code}
        </pre>
      )}

      {!success && execution.stderr && (
        <div className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          <div className="font-medium">Error:</div>
          <pre className="mt-1 whitespace-pre-wrap">{execution.stderr}</pre>
        </div>
      )}
    </div>
  );
}
