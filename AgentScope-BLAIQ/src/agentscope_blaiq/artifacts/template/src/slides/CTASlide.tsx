import React from "react";

interface Props {
  headline: string;
  body?: string;
  cta_text?: string;
  cta_url?: string;
  index: number;
  total?: number;
}

export function CTASlide({ headline, body, cta_text, cta_url }: Props) {
  return (
    <section className="min-h-screen flex flex-col items-center justify-center text-center px-8 py-24">
      <h2 className="font-heading text-[clamp(2rem,5vw,4rem)] font-bold tracking-[-0.02em] max-w-3xl">
        {headline}
      </h2>
      {body && (
        <p className="mt-6 text-brand-muted max-w-xl text-lg leading-relaxed">{body}</p>
      )}
      {cta_text && (
        <a
          href={cta_url || "#"}
          className="mt-10 inline-flex items-center gap-2.5 px-10 py-4 rounded-full bg-gradient-to-r from-brand-accent to-purple-500 text-white font-bold text-lg tracking-tight shadow-[0_8px_32px_rgba(108,99,255,0.4)] hover:shadow-[0_12px_40px_rgba(108,99,255,0.5)] transition-shadow"
        >
          {cta_text}
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </a>
      )}
    </section>
  );
}
