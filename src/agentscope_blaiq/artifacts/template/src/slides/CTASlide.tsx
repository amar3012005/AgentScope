import React from "react";

interface Props {
  headline: string;
  body?: string;
  cta_text?: string;
  cta_url?: string;
  index: number;
  total?: number;
}

export function CTASlide({ headline, body, cta_text, cta_url }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center text-center px-8 py-24 overflow-hidden">
      {/* Radial gradient behind CTA area */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse at center 60%, rgba(108, 99, 255, 0.08) 0%, transparent 60%)`,
        }}
      />

      <div className="mesh-bg-pulse" />

      <div className="relative z-10">
        <h2 className="font-heading text-[clamp(2rem,5vw,4rem)] font-bold tracking-[-0.02em] max-w-3xl gradient-text animate-in">
          {headline}
        </h2>
        {body && (
          <p
            className="mt-6 text-brand-muted max-w-xl text-lg leading-relaxed mx-auto"
            style={{ animation: "typeReveal 0.8s ease-out 0.3s both" }}
          >
            {body}
          </p>
        )}
        {cta_text && (
          <div className="mt-10" style={{ animation: "fadeInUp 0.8s ease-out 0.5s both" }}>
            <a
              href={cta_url || "#"}
              className="cta-shimmer relative inline-flex items-center gap-2.5 px-10 py-4 rounded-full bg-gradient-to-r from-brand-accent to-brand-accent2 text-white font-bold text-lg tracking-tight transition-all duration-300 hover:scale-[1.02]"
              style={{
                boxShadow: `0 8px 32px rgba(108, 99, 255, 0.35)`,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.boxShadow =
                  "0 12px 48px rgba(108, 99, 255, 0.5), 0 0 20px rgba(108, 99, 255, 0.2)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.boxShadow =
                  "0 8px 32px rgba(108, 99, 255, 0.35)";
              }}
            >
              {cta_text}
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </a>
          </div>
        )}
      </div>
    </section>
  );
}
