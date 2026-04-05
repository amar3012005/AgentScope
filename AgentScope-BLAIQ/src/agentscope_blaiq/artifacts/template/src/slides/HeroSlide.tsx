import React from "react";

interface Props {
  tag?: string;
  headline: string;
  subheadline?: string;
  body?: string;
  index: number;
  total?: number;
}

export function HeroSlide({ tag, headline, subheadline, body }: Props) {
  return (
    <section className="relative min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-brand-accent/10 via-transparent to-transparent pointer-events-none" />
      <div className="relative z-10 max-w-4xl">
        {tag && (
          <span className="inline-block mb-6 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.2em] border border-brand-accent/30 rounded-full text-brand-accent bg-brand-accent/10">
            {tag}
          </span>
        )}
        <h1 className="font-heading text-[clamp(2.5rem,6vw,5rem)] font-extrabold tracking-[-0.03em] leading-[1.05] bg-gradient-to-r from-white via-brand-primary to-brand-accent bg-clip-text text-transparent">
          {headline}
        </h1>
        {subheadline && (
          <p className="mt-6 text-[clamp(1rem,2vw,1.3rem)] text-brand-muted max-w-[65ch] leading-relaxed">
            {subheadline}
          </p>
        )}
        {body && (
          <p className="mt-4 text-brand-muted/70 max-w-[55ch] leading-relaxed">
            {body}
          </p>
        )}
      </div>
    </section>
  );
}
