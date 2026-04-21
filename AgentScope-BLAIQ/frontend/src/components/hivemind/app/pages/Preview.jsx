import { useCallback, useRef, useState } from 'react';
import { FileCode2, GripVertical, ShieldCheck, Download, ListTodo, RefreshCcw } from 'lucide-react';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';
import AgentPlan from '../shared/agent-plan';
import ContentDirectorLoader from '../shared/content-director-loader';

export default function Preview() {
  const { previewHtml, schema, governance, renderState, agentPlan, reRunWorkflow, activeTaskId } = useBlaiqWorkspace();
  const containerRef = useRef(null);
  const [sidebarWidth, setSidebarWidth] = useState(360);
  const [activeTab, setActiveTab] = useState('schema');
  const dragging = useRef(false);

  const handleDownload = useCallback(async (format) => {
    if (!previewHtml || !containerRef.current) return;

    const iframe = containerRef.current.querySelector('iframe');
    if (!iframe) return;

    try {
      // Send message to iframe to trigger capture
      const message = { type: 'capture', format };
      iframe.contentWindow.postMessage(message, '*');
    } catch (err) {
      console.error('Download failed:', err);
    }
  }, [previewHtml]);

  const onMouseDown = useCallback((e) => {
    e.preventDefault();
    dragging.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidth;

    const onMouseMove = (me) => {
      const delta = startX - me.clientX;
      const newWidth = Math.max(240, Math.min(600, startWidth + delta));
      setSidebarWidth(newWidth);
    };

    const onMouseUp = () => {
      dragging.current = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [sidebarWidth]);

  return (
    <div
      ref={containerRef}
      className="flex h-full min-h-0 gap-0 p-5 md:p-7"
      style={{ overflow: 'hidden' }}
    >
      {/* Preview panel — takes remaining space */}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col rounded-[32px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-4 shadow-[0_22px_50px_rgba(0,0,0,0.06)]">
        <div className="mb-4 flex shrink-0 items-center justify-between">
          <div>
            <div className="text-[11px] font-mono uppercase tracking-[0.12em] text-[#7a7267]">Artifact</div>
            <div className="mt-1 font-['Space_Grotesk'] text-lg font-semibold text-[#111827]">
              {previewHtml ? 'Live preview' : renderState.loading ? 'Rendering pages' : 'Preview pending'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {previewHtml && (
              <>
                <button
                  onClick={() => reRunWorkflow(activeTaskId)}
                  disabled={renderState.loading}
                  className=\"flex items-center gap-1.5 rounded-full border border-[#e3e0db] bg-white px-3 py-1.5 text-[11px] text-[#4b5563] hover:bg-[#f5f5f5] disabled:opacity-50 transition-all\"
                  title=\"Re-run style generation (keeps research)\"
                >
                  <RefreshCcw size={14} className={renderState.loading ? 'animate-spin' : ''} />
                  <span>Retry Style</span>
                </button>
                <div className=\"relative group\">
                  <button className=\"flex items-center gap-1.5 rounded-full border border-[#e3e0db] bg-white px-3 py-1.5 text-[11px] text-[#4b5563] hover:bg-[#f5f5f5]\">
                    <Download size={14} />
                    <span>Download</span>
                  </button>
                  <div className=\"absolute right-0 top-full mt-1 hidden flex-col gap-1 rounded-lg border border-[#e3e0db] bg-white py-1 shadow-lg group-hover:flex\">
                    <button
                      onClick={() => handleDownload('pdf')}
                      className=\"whitespace-nowrap px-3 py-1.5 text-xs text-[#4b5563] hover:bg-[#f5f5f5]\"
                    >
                      As PDF
                    </button>
                    <button
                      onClick={() => handleDownload('image')}
                      className=\"whitespace-nowrap px-3 py-1.5 text-xs text-[#4b5563] hover:bg-[#f5f5f5]\"
                    >
                      As Image
                    </button>
                  </div>
                </div>
              </>
            )}
            <div className="rounded-full border border-[#e3e0db] bg-white px-3 py-1.5 text-[11px] text-[#4b5563]">{renderState.artifactKind || 'content'}</div>
          </div>
        </div>
        {/* Progress bar or Content Director Loader */}
        {renderState.isContentDirectorActive ? (
          <div className="mb-3 shrink-0">
            <ContentDirectorLoader isVisible={true} />
          </div>
        ) : renderState.loading && renderState.total > 0 ? (
          <div className="mb-3 shrink-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-[#7a7267] font-mono uppercase tracking-wider">Rendering slides</span>
              <span className="text-[10px] text-[#7a7267]">{renderState.section} / {renderState.total}</span>
            </div>
            <div className="w-full rounded-full bg-[#e3e0db]">
              <div
                className="h-1.5 rounded-full bg-[#ff5c4b] transition-all duration-500"
                style={{ width: `${Math.min(100, Math.max(4, (renderState.section / Math.max(1, renderState.total)) * 100))}%` }}
              />
            </div>
          </div>
        ) : null}
        <div className="min-h-0 flex-1 rounded-[26px] border border-[#e3e0db] bg-white" style={{ overflow: 'hidden', position: 'relative' }}>
          {previewHtml ? (
            <iframe
              title="Artifact preview"
              srcDoc={previewHtml}
              className="border-0"
              style={{ display: 'block', width: '100%', height: '100%', overflow: 'auto' }}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center text-sm text-[#6b7280]">
              <div className="font-semibold text-[#111827]">
                {renderState.loading ? 'Rendering is in progress…' : 'Preview opens as soon as the first slide is ready.'}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Draggable resize handle */}
      <div
        className="flex w-4 shrink-0 cursor-col-resize items-center justify-center max-xl:hidden"
        onMouseDown={onMouseDown}
      >
        <div className="flex h-12 w-4 items-center justify-center rounded-full transition-colors hover:bg-[#e3e0db]">
          <GripVertical size={12} className="text-[#c7bfb3]" />
        </div>
      </div>

      {/* Right sidebar — resizable width */}
      <aside
        className="flex min-h-0 flex-col gap-4 overflow-y-auto pb-2 max-xl:hidden"
        style={{ width: sidebarWidth, flexShrink: 0, scrollbarGutter: 'stable' }}
      >
        {/* Tab navigation */}
        <div className="flex rounded-[24px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-1">
          <button
            onClick={() => setActiveTab('schema')}
            className={`flex-1 flex items-center justify-center gap-1.5 rounded-[20px] px-3 py-2 text-xs font-medium transition-all ${
              activeTab === 'schema'
                ? 'bg-white text-[#111827] shadow-sm'
                : 'text-[#6b7280] hover:text-[#111827]'
            }`}
          >
            <FileCode2 size={14} />
            Schema
          </button>
          <button
            onClick={() => setActiveTab('governance')}
            className={`flex-1 flex items-center justify-center gap-1.5 rounded-[20px] px-3 py-2 text-xs font-medium transition-all ${
              activeTab === 'governance'
                ? 'bg-white text-[#111827] shadow-sm'
                : 'text-[#6b7280] hover:text-[#111827]'
            }`}
          >
            <ShieldCheck size={14} />
            Governance
          </button>
          <button
            onClick={() => setActiveTab('plan')}
            className={`flex-1 flex items-center justify-center gap-1.5 rounded-[20px] px-3 py-2 text-xs font-medium transition-all ${
              activeTab === 'plan'
                ? 'bg-white text-[#111827] shadow-sm'
                : 'text-[#6b7280] hover:text-[#111827]'
            }`}
          >
            <ListTodo size={14} />
            Plan
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'schema' && (
          <div className="rounded-[30px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-5 shadow-[0_18px_44px_rgba(0,0,0,0.05)]">
            <div className="mb-3 flex items-center gap-2">
              <FileCode2 size={16} className="text-[#ff5c4b]" />
              <div className="font-['Space_Grotesk'] text-lg font-semibold">Schema</div>
            </div>
            {schema ? <pre className="overflow-auto rounded-[24px] bg-white p-3 text-xs leading-relaxed text-[#4b5563]">{JSON.stringify(schema, null, 2)}</pre> : <div className="text-sm text-[#6b7280]">Schema is not available yet.</div>}
          </div>
        )}

        {activeTab === 'governance' && (
          <div className="rounded-[30px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-5 shadow-[0_18px_44px_rgba(0,0,0,0.05)]">
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck size={16} className="text-[#ff5c4b]" />
              <div className="font-['Space_Grotesk'] text-lg font-semibold">Governance</div>
            </div>
            {governance ? (
              <div className="space-y-3">
                <div className={`rounded-[22px] px-3 py-2 text-sm font-medium ${governance.approved ? 'bg-emerald-50 text-emerald-700' : 'bg-[rgba(255,92,75,0.12)] text-[#ff5c4b]'}`}>
                  {governance.approved ? 'Validation passed' : 'Review required'}
                </div>
                <div className="rounded-[22px] bg-white p-3">
                  <div className="text-sm font-medium text-[#111827]">Readiness score</div>
                  <div className="mt-1 text-xs text-[#6b7280]">{governance.readiness_score}</div>
                </div>
                {(governance.issues || []).map((issue, index) => (
                  <div key={`${issue}-${index}`} className="rounded-[22px] bg-white p-3">
                    <div className="text-sm font-medium text-[#111827]">Issue {index + 1}</div>
                    <div className="mt-1 text-xs text-[#6b7280]">{issue}</div>
                  </div>
                ))}
                {(governance.notes || []).map((note, index) => (
                  <div key={`${note}-${index}`} className="rounded-[22px] bg-white p-3">
                    <div className="text-sm font-medium text-[#111827]">Note {index + 1}</div>
                    <div className="mt-1 text-xs text-[#6b7280]">{note}</div>
                  </div>
                ))}
              </div>
            ) : <div className="text-sm text-[#6b7280]">Governance appears after artifact evaluation.</div>}
          </div>
        )}

        {activeTab === 'plan' && (
          <div className="rounded-[30px] border border-[rgba(0,0,0,0.06)] bg-[#faf9f4] p-0 shadow-[0_18px_44px_rgba(0,0,0,0.05)] overflow-hidden">
            <AgentPlan tasks={agentPlan} />
          </div>
        )}
      </aside>
    </div>
  );
}
