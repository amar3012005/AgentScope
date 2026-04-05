import React from "react";

interface Props {
  title: string;
  subtitle?: string;
  bullets: string[];
  index: number;
  total?: number;
}

export function BulletSlide({ title, subtitle, bullets }: Props) {
  return (
    <section className="min-h-screen flex flex-col justify-center px-[clamp(2rem,10vw,8rem)] py-24">
      <h2 className="font-heading text-[clamp(1.8rem,4vw,3rem)] font-bold tracking-[-0.02em] mb-2">
        {title}
      </h2>
      {subtitle && <p className="text-brand-muted mb-10 max-w-[50ch]">{subtitle}</p>}
      <ul className="space-y-3 max-w-2xl">
        {bullets.map((item, i) => (
          <li
            key={i}
            className="px-5 py-4 rounded-xl bg-brand-surface border-l-[3px] border-brand-accent text-brand-primary/90 leading-relaxed"
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
