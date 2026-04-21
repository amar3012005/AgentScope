import React from "react";

interface Props {
  quote: string;
  attribution?: string;
  role?: string;
  index: number;
  total?: number;
}

export function QuoteSlide({ quote, attribution, role }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden">
      <div className="mesh-bg" />

      <div className="relative max-w-3xl w-full animate-in">
        {/* Glass card */}
        <div className="glass-strong p-12 rounded-3xl relative">
          {/* Large decorative quotation mark */}
          <div
            className="absolute -top-6 left-8 text-[8rem] leading-none font-heading text-brand-accent/10 select-none pointer-events-none"
            style={{ fontFamily: "Georgia, serif" }}
          >
            &ldquo;
          </div>

          {/* Quote text */}
          <p className="relative text-[clamp(1.2rem,2.5vw,1.8rem)] text-brand-primary/90 leading-relaxed italic font-heading">
            {quote}
          </p>

          {/* Attribution with rule separator */}
          {attribution && (
            <div className="mt-8">
              <div className="w-12 h-px bg-gradient-to-r from-brand-accent to-brand-accent2 mb-4" />
              <div className="text-sm text-brand-muted">
                <span className="text-brand-primary/70">{attribution}</span>
                {role && (
                  <span className="text-brand-muted/60">{" "}&middot; {role}</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
