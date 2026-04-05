import React from "react";

interface StatItem {
  value: string;
  label: string;
  source?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  items: StatItem[];
  index: number;
  total?: number;
}

export function DataGridSlide({ title, subtitle, items }: Props) {
  return (
    <section className="min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24">
      <h2 className="font-heading text-[clamp(1.8rem,4vw,3rem)] font-bold tracking-[-0.02em] mb-2">
        {title}
      </h2>
      {subtitle && <p className="text-brand-muted mb-10 max-w-[50ch]">{subtitle}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {items.map((item, i) => (
          <div
            key={i}
            className="relative p-7 rounded-2xl border border-brand-border bg-brand-surface overflow-hidden group hover:border-brand-accent/30 transition-colors"
          >
            <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-brand-accent to-brand-accent2 opacity-0 group-hover:opacity-100 transition-opacity" />
            <div className="text-[clamp(2rem,5vw,3.5rem)] font-extrabold tracking-[-0.03em] text-brand-accent">
              {item.value}
            </div>
            <div className="mt-1 text-sm text-brand-muted">{item.label}</div>
            {item.source && (
              <span className="mt-3 inline-block text-[10px] text-brand-muted/60 border border-brand-border rounded-full px-2 py-0.5">
                {item.source}
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
