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

export function EvidenceSlide({ title, items }: Props) {
  return (
    <section className="min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24">
      <h2 className="font-heading text-[clamp(1.8rem,4vw,3rem)] font-bold tracking-[-0.02em] mb-10">
        {title}
      </h2>
      <div className="space-y-4 max-w-3xl">
        {items.map((item, i) => (
          <div key={i} className="p-5 rounded-xl bg-brand-surface/80 border border-brand-border">
            <p className="text-brand-primary/85 leading-relaxed">{item.finding}</p>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[10px] text-brand-muted/60 border border-brand-border rounded-full px-2.5 py-0.5">
                {item.source}
              </span>
              {item.confidence !== undefined && (
                <span className="text-[10px] text-brand-accent/70">
                  {Math.round(item.confidence * 100)}% confidence
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
