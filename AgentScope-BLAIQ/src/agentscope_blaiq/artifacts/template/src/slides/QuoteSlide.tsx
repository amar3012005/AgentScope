import React from "react";

interface Props {
  quote: string;
  attribution?: string;
  role?: string;
  index: number;
  total?: number;
}

export function QuoteSlide({ quote, attribution, role }: Props) {
  return (
    <section className="min-h-screen flex flex-col items-center justify-center px-[clamp(2rem,10vw,8rem)] py-24">
      <div className="relative max-w-3xl p-10 rounded-3xl border border-brand-border/50 bg-gradient-to-br from-brand-surface to-brand-bg">
        <div className="absolute -top-4 left-10 text-6xl text-brand-accent/20 font-heading">"</div>
        <p className="text-[clamp(1.2rem,2.5vw,1.8rem)] text-brand-primary/90 leading-relaxed italic font-heading">
          {quote}
        </p>
        {attribution && (
          <div className="mt-6 text-sm text-brand-muted">
            — {attribution}{role ? `, ${role}` : ""}
          </div>
        )}
      </div>
    </section>
  );
}
