import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ProgressiveRenderer } from "../../../shared/orchestrator/progressive-renderer";
import { SlideNavigator } from "./SlideNavigator";
import { CodeStreamPane } from "./CodeStreamPane";
import type { SectionFragment } from "../../../shared/orchestrator/types";

interface ArtifactPreviewPaneProps {
  threadId: string;
  html: string;
  sections?: SectionFragment[];
  viewMode?: "preview" | "code" | "split";
  artifactKind?: string;
  totalSections?: number;
  currentSlide?: number;
  slideTitles?: string[];
  loading?: boolean;
  loadingLabel?: string;
  onViewModeChange?: (mode: "preview" | "code" | "split") => void;
  onSlideNavigate?: (slideIndex: number) => void;
}

// Minimal base shell for progressive rendering when backend doesn't provide one
const FALLBACK_BASE_SHELL = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://unpkg.com/@tailwindcss/browser@4"></script>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
body { font-family: 'Manrope', sans-serif; background: #050505; color: #F5F5F1; margin: 0; }
h1,h2,h3,h4,h5,h6 { font-family: 'Cormorant Garamond', serif; }
.vangogh-section { opacity: 0; animation: fadeInUp 0.6s ease-out forwards; }
@keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body class="min-h-screen">
<div id="vangogh-root"></div>
<script>
mermaid.initialize({ theme: 'dark', startOnLoad: false });
function initVangoghCharts(container) {
  var root = container || document;
  root.querySelectorAll('canvas[data-chart-config]').forEach(function(c) {
    if (c._chartInstance) return;
    try { c._chartInstance = new Chart(c, JSON.parse(c.getAttribute('data-chart-config'))); } catch(e) {}
  });
  mermaid.run({ querySelector: '.mermaid' });
}
document.addEventListener('DOMContentLoaded', function() { initVangoghCharts(); });
window.addEventListener('message', function(e) {
  if (e.data && e.data.type === 'navigate-slide') {
    var t = document.querySelector('[data-slide="' + e.data.slideIndex + '"]');
    if (t) t.scrollIntoView({ behavior: 'smooth' });
  }
});
</script>
</body>
</html>`;

export function ArtifactPreviewPane({
  threadId,
  html,
  sections = [],
  viewMode = "preview",
  artifactKind = "",
  totalSections = 0,
  currentSlide = 0,
  slideTitles = [],
  loading = false,
  loadingLabel = "",
  onViewModeChange,
  onSlideNavigate,
}: ArtifactPreviewPaneProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const rendererRef = useRef<ProgressiveRenderer | null>(null);
  const [renderedCount, setRenderedCount] = useState(0);

  // Initialize progressive renderer when sections start arriving
  useEffect(() => {
    if (sections.length > 0 && iframeRef.current && !rendererRef.current) {
      const renderer = new ProgressiveRenderer(iframeRef.current);
      renderer.initialize(FALLBACK_BASE_SHELL);
      rendererRef.current = renderer;
    }
  }, [sections.length]);

  // Append new sections as they arrive
  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer || sections.length <= renderedCount) return;

    // Append only new sections
    for (let i = renderedCount; i < sections.length; i++) {
      const section = sections[i];
      renderer.appendSection(section.sectionId, section.htmlFragment);
    }
    setRenderedCount(sections.length);
  }, [sections, renderedCount]);

  // Reset renderer when thread changes
  useEffect(() => {
    rendererRef.current = null;
    setRenderedCount(0);
  }, [threadId]);

  const handleSlideNavigate = useCallback(
    (slideIndex: number) => {
      rendererRef.current?.navigateToSlide(slideIndex);
      onSlideNavigate?.(slideIndex);
    },
    [onSlideNavigate]
  );

  const showSlideNav =
    (artifactKind === "pitch_deck" || artifactKind === "keynote") &&
    sections.length > 1;

  const progress =
    totalSections > 0 ? Math.round((sections.length / totalSections) * 100) : 0;

  const hasContent = html || sections.length > 0;

  return (
    <section className="panel-card artifact-pane">
      <div className="panel-card__header">
        <span>Vangogh Preview</span>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          {onViewModeChange && (
            <div className="artifact-pane__view-toggle">
              {(["preview", "code", "split"] as const).map((mode) => (
                <button
                  key={mode}
                  className={`artifact-pane__view-btn${viewMode === mode ? " artifact-pane__view-btn--active" : ""}`}
                  onClick={() => onViewModeChange(mode)}
                >
                  {mode === "preview" ? "Preview" : mode === "code" ? "Code" : "Split"}
                </button>
              ))}
            </div>
          )}
          {threadId && (
            <Link className="panel-card__link" to={`/artifacts/${threadId}`}>
              Expand
            </Link>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {loading && totalSections > 0 && (
        <div className="artifact-pane__progress">
          <div
            className="artifact-pane__progress-bar"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {/* Loading label */}
      {loading && loadingLabel && (
        <div className="artifact-pane__loading-label">{loadingLabel}</div>
      )}

      {hasContent ? (
        <div
          className={`artifact-pane__content${viewMode === "split" ? " artifact-pane__content--split" : ""}`}
        >
          {/* Code view */}
          {(viewMode === "code" || viewMode === "split") && (
            <CodeStreamPane sections={sections} fullHtml={html} />
          )}

          {/* Preview iframe */}
          {(viewMode === "preview" || viewMode === "split") && (
            <iframe
              ref={iframeRef}
              className="artifact-pane__frame"
              title="Vangogh artifact preview"
              sandbox="allow-scripts allow-same-origin"
              srcDoc={sections.length === 0 ? html : undefined}
            />
          )}
        </div>
      ) : (
        <p className="panel-card__empty">
          No artifact rendered yet. Content workflows will appear here.
        </p>
      )}

      {/* Slide navigator */}
      {showSlideNav && (
        <SlideNavigator
          totalSlides={sections.length}
          currentSlide={currentSlide}
          slideTitles={slideTitles}
          onNavigate={handleSlideNavigate}
        />
      )}
    </section>
  );
}
