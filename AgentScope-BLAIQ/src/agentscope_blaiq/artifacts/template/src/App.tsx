import React from "react";
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

export default function App() {
  const { slides, title } = slidesData;
  return (
    <div className="min-h-screen bg-brand-bg text-brand-primary">
      {slides.map((slide: any, i: number) => {
        const SlideComponent = SLIDE_MAP[slide.type] || BulletSlide;
        return <SlideComponent key={i} {...slide} index={i} total={slides.length} />;
      })}
    </div>
  );
}
