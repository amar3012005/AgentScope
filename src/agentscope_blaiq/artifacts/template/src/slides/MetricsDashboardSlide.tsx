import React from "react";

interface MetricCard {
  value: string;
  label: string;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  comparison?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  metrics: MetricCard[];
  index: number;
  total?: number;
}

export function MetricsDashboardSlide({ title, subtitle, metrics }: Props): JSX.Element {
  return (
    <section className="relative min-h-screen flex flex-col px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden bg-gradient-to-br from-[#f8fafc] via-[#f1f5f9] to-[#e2e8f0]">
      {/* Header */}
      <div className="relative z-10 mb-12">
        <h2 className="font-heading text-[clamp(2rem,5vw,3.5rem)] font-bold tracking-[-0.03em] text-[#0f172a] mb-3">
          {title}
        </h2>
        {subtitle && (
          <p className="text-[#64748b] text-lg max-w-[60ch]">{subtitle}</p>
        )}
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 w-full">
        {metrics.map((metric, i) => (
          <div
            key={i}
            className="group relative bg-white rounded-3xl p-8 shadow-[0_4px_24px_rgba(0,0,0,0.06)] hover:shadow-[0_8px_48px_rgba(0,0,0,0.12)] transition-all duration-500 overflow-hidden"
            style={{
              opacity: 0,
              animation: `slideUp 0.7s ease-out ${0.1 + i * 0.12}s forwards`,
            }}
          >
            {/* Subtle top accent */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#3b82f6] via-[#8b5cf6] to-[#ec4899]" />

            {/* Metric value */}
            <div className="relative z-10">
              <div className="text-[clamp(2.5rem,6vw,4rem)] font-extrabold tracking-[-0.04em] text-[#0f172a] leading-none">
                {metric.value}
              </div>

              {/* Label */}
              <div className="mt-4 text-sm font-medium text-[#64748b] uppercase tracking-wider">
                {metric.label}
              </div>

              {/* Trend indicator */}
              {metric.trend && (
                <div className="mt-5 flex items-center gap-3">
                  <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold ${
                    metric.trend === 'up'
                      ? 'bg-emerald-50 text-emerald-700'
                      : metric.trend === 'down'
                      ? 'bg-red-50 text-red-700'
                      : 'bg-gray-100 text-gray-600'
                  }`}>
                    {metric.trend === 'up' && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                      </svg>
                    )}
                    {metric.trend === 'down' && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                      </svg>
                    )}
                    {metric.trend === 'neutral' && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 12h14" />
                      </svg>
                    )}
                    <span>{metric.trendValue}</span>
                  </div>
                  {metric.comparison && (
                    <span className="text-sm text-[#94a3b8]">{metric.comparison}</span>
                  )}
                </div>
              )}
            </div>

            {/* Subtle background decoration */}
            <div className="absolute -bottom-8 -right-8 w-32 h-32 bg-gradient-to-br from-[#3b82f6]/5 to-[#8b5cf6]/5 rounded-full blur-2xl" />
          </div>
        ))}
      </div>
    </section>
  );
}
