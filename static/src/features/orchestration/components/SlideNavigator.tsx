import { useCallback, useEffect } from "react";

interface SlideNavigatorProps {
  totalSlides: number;
  currentSlide: number;
  slideTitles: string[];
  onNavigate: (slideIndex: number) => void;
}

export function SlideNavigator({
  totalSlides,
  currentSlide,
  slideTitles,
  onNavigate,
}: SlideNavigatorProps) {
  const goTo = useCallback(
    (delta: number) => {
      const next = Math.max(0, Math.min(totalSlides - 1, currentSlide + delta));
      if (next !== currentSlide) onNavigate(next);
    },
    [currentSlide, totalSlides, onNavigate]
  );

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        goTo(1);
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        goTo(-1);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [goTo]);

  if (totalSlides <= 1) return null;

  const title = slideTitles[currentSlide] || `Slide ${currentSlide + 1}`;

  return (
    <nav className="slide-navigator">
      <button
        className="slide-navigator__btn"
        onClick={() => goTo(-1)}
        disabled={currentSlide === 0}
        aria-label="Previous slide"
      >
        &#8249;
      </button>
      <span className="slide-navigator__label">
        {currentSlide + 1} / {totalSlides}
        <span className="slide-navigator__title">{title}</span>
      </span>
      <button
        className="slide-navigator__btn"
        onClick={() => goTo(1)}
        disabled={currentSlide === totalSlides - 1}
        aria-label="Next slide"
      >
        &#8250;
      </button>
    </nav>
  );
}
