import React from "react";

interface Props {
  tag?: string;
  headline: string;
  subheadline?: string;
  body?: string;
  index: number;
  total?: number;
}

export function HeroSlide({ tag, headline, subheadline, body }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden">
      {/* Animated mesh gradient background */}
      <div className="mesh-bg-pulse" />

      {/* Decorative geometric circle */}
      <div
        className="absolute -right-32 top-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.04] pointer-events-none"
        style={{
          background: `radial-gradient(circle, var(--brand-accent) 0%, transparent 70%)`,
        }}
      />

      {/* Decorative horizontal line */}
      <div className="absolute left-[clamp(2rem,10vw,8rem)] top-1/3 w-16 h-px bg-gradient-to-r from-brand-accent to-transparent opacity-40" />

      <div className="relative z-10 max-w-4xl">
        {tag && (
          <span
            className="inline-block mb-6 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.2em] border border-brand-accent/30 rounded-full text-brand-accent bg-brand-accent/10 animate-in-scale"
            style={{
              boxShadow: `0 0 20px rgba(108, 99, 255, 0.15), inset 0 0 12px rgba(108, 99, 255, 0.05)`,
            }}
          >
            {tag}
          </span>
        )}
        <h1 className="font-heading text-[clamp(2.5rem,6vw,5rem)] font-extrabold tracking-[-0.03em] leading-[1.05] bg-gradient-to-r from-white via-brand-primary to-brand-accent bg-clip-text text-transparent animate-in">
          {headline}
        </h1>
        {subheadline && (
          <p
            className="mt-6 text-[clamp(1rem,2vw,1.3rem)] text-brand-muted max-w-[65ch] leading-relaxed"
            style={{ animation: "typeReveal 0.8s ease-out 0.4s both" }}
          >
            {subheadline}
          </p>
        )}
        {body && (
          <p
            className="mt-4 text-brand-muted/70 max-w-[55ch] leading-relaxed"
            style={{ animation: "typeReveal 0.8s ease-out 0.6s both" }}
          >
            {body}
          </p>
        )}
      </div>
    </section>
  );
}
