import React from "react";

interface EvidenceItem {
  finding: string;
  source: string;
  confidence?: number;
}

interface Props {
  title: string;
  items: EvidenceItem[];
  index: number;
  total?: number;
}

export function EvidenceSlide({ title, items }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden">
      <div className="mesh-bg" />
      <div className="relative z-10">
        <h2 className="font-heading text-[clamp(1.8rem,4vw,3rem)] font-bold tracking-[-0.02em] mb-10 animate-in">
          {title}
        </h2>
        <div className="space-y-4 max-w-3xl">
          {items.map((item, i) => (
            <div
              key={i}
              className="group relative p-5 rounded-xl bg-brand-surface/80 border border-brand-border overflow-hidden transition-all duration-300 hover:border-brand-accent/20"
              style={{
                opacity: 0,
                animation: `fadeInUp 0.5s ease-out ${0.15 + i * 0.1}s forwards`,
              }}
            >
              {/* Left border gradient */}
              <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-gradient-to-b from-brand-accent to-brand-accent2 opacity-50 group-hover:opacity-100 transition-opacity" />

              {/* Glass effect on hover */}
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 glass pointer-events-none rounded-xl" />

              <p className="relative text-brand-primary/85 leading-relaxed">{item.finding}</p>

              <div className="relative mt-3 flex items-center gap-3">
                {/* Source chip with micro icon */}
                <span className="inline-flex items-center gap-1.5 text-[10px] text-brand-muted/70 border border-brand-border rounded-full px-2.5 py-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-brand-accent/60" />
                  {item.source}
                </span>
                {item.confidence !== undefined && (
                  <span className="text-[10px] text-brand-accent/70">
                    {Math.round(item.confidence * 100)}%
                  </span>
                )}
              </div>

              {/* Confidence indicator bar */}
              {item.confidence !== undefined && (
                <div className="mt-3 confidence-bar">
                  <div
                    className="confidence-bar-fill"
                    style={{ width: `${Math.round(item.confidence * 100)}%` }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
