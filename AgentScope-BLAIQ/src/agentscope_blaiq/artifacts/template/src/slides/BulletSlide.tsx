import React from "react";

interface Props {
  title: string;
  subtitle?: string;
  bullets: string[];
  index: number;
  total?: number;
}

export function BulletSlide({ title, subtitle, bullets }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden">
      <div className="mesh-bg" />
      <div className="relative z-10">
        <h2 className="font-heading text-[clamp(1.8rem,4vw,3rem)] font-bold tracking-[-0.02em] mb-2 animate-in">
          {title}
        </h2>
        {subtitle && (
          <p className="text-brand-muted mb-10 max-w-[50ch] animate-in stagger-1">{subtitle}</p>
        )}
        <ul className="space-y-3 max-w-2xl">
          {bullets.map((item, i) => (
            <li
              key={i}
              className="group relative px-5 py-4 rounded-xl bg-brand-surface border border-brand-border text-brand-primary/90 leading-relaxed transition-all duration-300 hover:bg-brand-surface/80 hover:border-brand-accent/30"
              style={{
                opacity: 0,
                animation: `fadeInUp 0.5s ease-out ${0.15 + i * 0.1}s forwards`,
                borderLeftWidth: "3px",
                borderLeftColor: "transparent",
                borderImage: `linear-gradient(to bottom, var(--brand-accent), var(--brand-accent2)) 1`,
                borderImageSlice: "0 0 0 1",
              }}
            >
              {/* Styled number/marker */}
              <span className="absolute left-[-1px] top-0 bottom-0 w-[3px] rounded-full bg-gradient-to-b from-brand-accent to-brand-accent2 opacity-80 group-hover:opacity-100 transition-opacity" />
              <div className="flex items-start gap-3">
                <span className="flex-shrink-0 mt-0.5 text-brand-accent/70 text-sm font-mono">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span>{item}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
