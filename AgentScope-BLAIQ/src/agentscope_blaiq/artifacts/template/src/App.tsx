import React, { useCallback, useEffect, useRef, useState } from "react";
import slidesData from "./slides.json";
import { HeroSlide } from "./slides/HeroSlide";
import { DataGridSlide } from "./slides/DataGridSlide";
import { BulletSlide } from "./slides/BulletSlide";
import { EvidenceSlide } from "./slides/EvidenceSlide";
import { CTASlide } from "./slides/CTASlide";
import { QuoteSlide } from "./slides/QuoteSlide";
import { MetricsDashboardSlide } from "./slides/MetricsDashboardSlide";
import { AnalysisChartSlide } from "./slides/AnalysisChartSlide";
import { DataTableSlide } from "./slides/DataTableSlide";
import { InsightCardsSlide } from "./slides/InsightCardsSlide";

// Message type for download requests from parent window
type CaptureMessage = { type: 'capture'; format: 'pdf' | 'png' };

const SLIDE_MAP: Record<string, React.FC<any>> = {
  hero: HeroSlide,
  data_grid: DataGridSlide,
  bullets: BulletSlide,
  evidence: EvidenceSlide,
  cta: CTASlide,
  quote: QuoteSlide,
  metrics_dashboard: MetricsDashboardSlide,
  analysis_chart: AnalysisChartSlide,
  data_table: DataTableSlide,
  insight_cards: InsightCardsSlide,
};

export default function App(): JSX.Element {
  const { slides, layout } = slidesData as { slides: any[]; layout?: string };
  const isPoster = layout === "poster";
  const totalSlides: number = slides.length;
  const containerRef = useRef<HTMLDivElement>(null);
  const [currentSlide, setCurrentSlide] = useState<number>(0);
  const [visibleSlides, setVisibleSlides] = useState<Set<number>>(new Set([0]));

  const goTo = useCallback(
    (index: number) => {
      if (isPoster) return;
      const clamped = Math.max(0, Math.min(index, totalSlides - 1));
      setCurrentSlide(clamped);
      const container = containerRef.current;
      if (container) {
        container.scrollTo({ left: clamped * container.clientWidth, behavior: "smooth" });
      }
    },
    [isPoster, totalSlides],
  );

  const next = useCallback(() => goTo(currentSlide + 1), [currentSlide, goTo]);
  const prev = useCallback(() => goTo(currentSlide - 1), [currentSlide, goTo]);

  /* Sync currentSlide on scroll */
  const handleScroll = useCallback(() => {
    if (isPoster) return;
    const container = containerRef.current;
    if (!container) return;
    const idx = Math.round(container.scrollLeft / container.clientWidth);
    setCurrentSlide(Math.min(idx, totalSlides - 1));
  }, [isPoster, totalSlides]);

  /* Entrance animations via IntersectionObserver */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const idx = Number(entry.target.getAttribute("data-slide-index"));
            if (!isNaN(idx)) setVisibleSlides((prev) => new Set(prev).add(idx));
          }
        });
      },
      { root: container, threshold: isPoster ? 0.15 : 0.3 },
    );
    container.querySelectorAll(".slide-panel").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [isPoster]);

  /* Keyboard + touch navigation */
  useEffect(() => {
    if (isPoster) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "PageDown") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp" || e.key === "PageUp") {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isPoster, next, prev]);

  /* Listen for capture messages from parent window */
  useEffect(() => {
    const handleMessage = async (event: MessageEvent<CaptureMessage>) => {
      if (event.data?.type === 'capture') {
        const { format } = event.data;
        const slideElement = isPoster
          ? containerRef.current?.querySelector(".poster-panel")
          : containerRef.current?.querySelector(`.slide-panel[data-slide-index="${currentSlide}"]`);
        if (!slideElement) return;

        try {
          // Wait for html2canvas to be available (loaded via injected script)
          const html2canvasLib = (window as any).html2canvas;
          if (!html2canvasLib) {
            console.warn('html2canvas not loaded');
            return;
          }

          const canvas = await html2canvasLib(slideElement, {
            backgroundColor: '#050505',
            scale: 2,
            useCORS: true,
          });

          const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);

          if (format === 'png') {
            const link = document.createElement('a');
            link.download = `slide-${currentSlide + 1}-${timestamp}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
          } else if (format === 'pdf') {
            const jspdfLib = (window as any).jspdf;
            if (!jspdfLib) {
              console.warn('jsPDF not loaded');
              return;
            }
            const { jsPDF } = jspdfLib;
            const pdf = new jsPDF({
              orientation: 'landscape',
              unit: 'px',
              format: [canvas.width, canvas.height],
            });
            pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, 0, canvas.width, canvas.height);
            pdf.save(`slide-${currentSlide + 1}-${timestamp}.pdf`);
          }
        } catch (err) {
          console.error('Capture failed:', err);
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [currentSlide, isPoster]);

  const progress = totalSlides > 1 ? (currentSlide / (totalSlides - 1)) * 100 : 100;

  return (
    <div className={`relative h-screen w-screen overflow-hidden bg-brand-bg text-brand-primary ${isPoster ? "poster-layout" : ""}`}>
      {!isPoster && (
        <div className="fixed top-0 left-0 right-0 h-[3px] z-50 bg-brand-surface/50">
          <div
            className="h-full bg-gradient-to-r from-brand-accent to-brand-accent2 transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {!isPoster && currentSlide > 0 && (
        <button
          onClick={prev}
          className="fixed left-4 top-1/2 -translate-y-1/2 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-brand-surface/60 border border-brand-border/40 text-brand-muted hover:text-brand-primary hover:bg-brand-surface hover:border-brand-accent/30 transition-all backdrop-blur-sm"
          aria-label="Previous slide"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
      )}
      {!isPoster && currentSlide < totalSlides - 1 && (
        <button
          onClick={next}
          className="fixed right-4 top-1/2 -translate-y-1/2 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-brand-surface/60 border border-brand-border/40 text-brand-muted hover:text-brand-primary hover:bg-brand-surface hover:border-brand-accent/30 transition-all backdrop-blur-sm"
          aria-label="Next slide"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
        </button>
      )}

      {!isPoster && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3">
          <div className="flex items-center gap-1.5 rounded-full bg-brand-surface/50 border border-brand-border/30 px-3 py-2 backdrop-blur-sm">
            {slides.map((_: any, i: number) => (
              <button
                key={i}
                onClick={() => goTo(i)}
                className={`h-2 rounded-full transition-all duration-300 ${
                  i === currentSlide
                    ? "w-6 bg-brand-accent"
                    : "w-2 bg-brand-muted/30 hover:bg-brand-muted/60"
                }`}
                aria-label={`Go to slide ${i + 1}`}
              />
            ))}
          </div>
          <span className="text-[10px] font-mono text-brand-muted/40 tracking-wider tabular-nums">
            {currentSlide + 1}/{totalSlides}
          </span>
        </div>
      )}

      <div
        ref={containerRef}
        className={isPoster ? "poster-panel flex h-full w-full flex-col overflow-hidden" : "flex h-full w-full overflow-x-auto scroll-smooth"}
        style={isPoster ? undefined : {
          scrollSnapType: "x mandatory",
          scrollbarWidth: "none",
          msOverflowStyle: "none",
          WebkitOverflowScrolling: "touch",
        }}
        onScroll={isPoster ? undefined : handleScroll}
      >
        {slides.map((slide: any, i: number) => {
          const SlideComponent = SLIDE_MAP[slide.type] || BulletSlide;
          const isVisible = visibleSlides.has(i);
          return (
            <div
              key={i}
              className={isPoster ? "slide-panel poster-section" : "slide-panel flex-shrink-0 w-screen h-screen overflow-y-auto"}
              data-slide-index={i}
              style={isPoster ? undefined : { scrollSnapAlign: "start" }}
            >
              <div
                className={`min-h-full transition-all duration-700 ${
                  isVisible ? "opacity-100 translate-x-0 translate-y-0" : isPoster ? "opacity-0 translate-y-6" : "opacity-0 translate-x-8"
                }`}
              >
                <SlideComponent {...slide} index={i} total={totalSlides} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Hide scrollbar */}
      <style>{`
        div::-webkit-scrollbar { display: none; }
      `}</style>
    </div>
  );
}
