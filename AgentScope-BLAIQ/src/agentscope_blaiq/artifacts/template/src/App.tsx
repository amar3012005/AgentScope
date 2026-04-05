import React, { useCallback, useEffect, useRef, useState } from "react";
import slidesData from "./slides.json";
import { HeroSlide } from "./slides/HeroSlide";
import { DataGridSlide } from "./slides/DataGridSlide";
import { BulletSlide } from "./slides/BulletSlide";
import { EvidenceSlide } from "./slides/EvidenceSlide";
import { CTASlide } from "./slides/CTASlide";
import { QuoteSlide } from "./slides/QuoteSlide";

const SLIDE_MAP: Record<string, React.FC<any>> = {
  hero: HeroSlide,
  data_grid: DataGridSlide,
  bullets: BulletSlide,
  evidence: EvidenceSlide,
  cta: CTASlide,
  quote: QuoteSlide,
};

export default function App(): JSX.Element {
  const { slides } = slidesData;
  const totalSlides: number = slides.length;
  const containerRef = useRef<HTMLDivElement>(null);
  const [currentSlide, setCurrentSlide] = useState<number>(0);
  const [progress, setProgress] = useState<number>(0);
  const [visibleSlides, setVisibleSlides] = useState<Set<number>>(new Set([0]));

  const updateProgress = useCallback((): void => {
    const container = containerRef.current;
    if (!container) return;
    const scrollTop = container.scrollTop;
    const scrollHeight = container.scrollHeight - container.clientHeight;
    const pct = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
    setProgress(pct);

    const slideIndex = Math.round(scrollTop / container.clientHeight);
    setCurrentSlide(Math.min(slideIndex, totalSlides - 1));
  }, [totalSlides]);

  /* Intersection Observer for entrance animations */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const idx = Number(entry.target.getAttribute("data-slide-index"));
            if (!isNaN(idx)) {
              setVisibleSlides((prev) => new Set(prev).add(idx));
            }
          }
        });
      },
      { root: container, threshold: 0.15 }
    );

    const wrappers = container.querySelectorAll(".slide-wrapper");
    wrappers.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, []);

  /* Keyboard navigation */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent): void => {
      const container = containerRef.current;
      if (!container) return;

      if (e.key === "ArrowDown" || e.key === "PageDown") {
        e.preventDefault();
        const next = Math.min(currentSlide + 1, totalSlides - 1);
        container.scrollTo({ top: next * container.clientHeight, behavior: "smooth" });
      } else if (e.key === "ArrowUp" || e.key === "PageUp") {
        e.preventDefault();
        const prev = Math.max(currentSlide - 1, 0);
        container.scrollTo({ top: prev * container.clientHeight, behavior: "smooth" });
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentSlide, totalSlides]);

  return (
    <div className="relative bg-brand-bg text-brand-primary">
      {/* Progress bar */}
      <div className="fixed top-0 left-0 right-0 h-1 z-50 bg-brand-surface">
        <div
          className="h-full bg-gradient-to-r from-brand-accent to-brand-accent2 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Slide counter */}
      <div className="fixed bottom-6 right-8 z-50 text-xs font-mono text-brand-muted/50 tracking-wider">
        {currentSlide + 1} / {totalSlides}
      </div>

      {/* Slides container */}
      <div
        ref={containerRef}
        className="slides-container"
        onScroll={updateProgress}
      >
        {slides.map((slide: any, i: number) => {
          const SlideComponent = SLIDE_MAP[slide.type] || BulletSlide;
          const isVisible = visibleSlides.has(i);
          return (
            <div
              key={i}
              className="slide-wrapper"
              data-slide-index={i}
            >
              <div
                className={`transition-opacity duration-700 ${isVisible ? "opacity-100" : "opacity-0"}`}
                style={{
                  animation: isVisible ? `fadeInUp 0.8s ease-out ${i * 0.05}s forwards` : "none",
                }}
              >
                <SlideComponent {...slide} index={i} total={totalSlides} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
