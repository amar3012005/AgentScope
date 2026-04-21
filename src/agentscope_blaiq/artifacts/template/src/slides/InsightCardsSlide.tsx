import React from "react";

interface InsightCard {
  title: string;
  finding: string;
  verdict: "positive" | "negative" | "warning" | "neutral";
  verdictLabel?: string;
  metrics?: { label: string; value: string }[];
  recommendation?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  insights: InsightCard[];
  index: number;
  total?: number;
}

export function InsightCardsSlide({ title, subtitle, insights }: Props): JSX.Element {
  const getVerdictStyles = (verdict: string) => {
    switch (verdict) {
      case "positive":
        return { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200" };
      case "negative":
        return { bg: "bg-red-50", text: "text-red-700", border: "border-red-200" };
      case "warning":
        return { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200" };
      default:
        return { bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-200" };
    }
  };

  return (
    <section className="relative min-h-screen flex flex-col px-[clamp(2rem,10vw,8rem)] py-24 overflow-hidden bg-gradient-to-br from-[#f8fafc] via-[#f1f5f9] to-[#e2e8f0]">
      {/* Header */}
      <div className="relative z-10 mb-10">
        <h2 className="font-heading text-[clamp(2rem,5vw,3.5rem)] font-bold tracking-[-0.03em] text-[#0f172a] mb-3">
          {title}
        </h2>
        {subtitle && (
          <p className="text-[#64748b] text-lg max-w-[60ch]">{subtitle}</p>
        )}
      </div>

      {/* Insights Grid */}
      <div className="space-y-6">
        {insights.map((insight, i) => {
          const verdictStyles = getVerdictStyles(insight.verdict);
          return (
            <div
              key={i}
              className="relative bg-white rounded-3xl p-8 shadow-[0_4px_24px_rgba(0,0,0,0.06)] overflow-hidden"
              style={{
                opacity: 0,
                animation: `slideUp 0.7s ease-out ${0.15 + i * 0.1}s forwards`,
              }}
            >
              {/* Left accent bar based on verdict */}
              <div
                className={`absolute left-0 top-0 bottom-0 w-1.5 ${
                  insight.verdict === "positive"
                    ? "bg-emerald-500"
                    : insight.verdict === "negative"
                    ? "bg-red-500"
                    : insight.verdict === "warning"
                    ? "bg-amber-500"
                    : "bg-slate-500"
                }`}
              />

              <div className="relative z-10">
                {/* Title and verdict row */}
                <div className="flex items-start justify-between gap-4 mb-4">
                  <h3 className="text-xl font-bold text-[#0f172a]">{insight.title}</h3>
                  <span
                    className={`px-4 py-1.5 rounded-full text-sm font-bold uppercase tracking-wider ${verdictStyles.bg} ${verdictStyles.text} border ${verdictStyles.border}`}
                  >
                    {insight.verdictLabel || insight.verdict}
                  </span>
                </div>

                {/* Finding */}
                <p className="text-[#475569] text-base leading-relaxed mb-6">{insight.finding}</p>

                {/* Metrics row */}
                {insight.metrics && insight.metrics.length > 0 && (
                  <div className="flex flex-wrap gap-4 mb-6">
                    {insight.metrics.map((metric, mi) => (
                      <div
                        key={mi}
                        className="px-5 py-3 bg-[#f8fafc] rounded-xl border border-[#e2e8f0]"
                      >
                        <div className="text-2xl font-bold text-[#0f172a]">{metric.value}</div>
                        <div className="text-xs text-[#64748b] font-medium uppercase tracking-wider mt-0.5">
                          {metric.label}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Recommendation */}
                {insight.recommendation && (
                  <div className={`px-5 py-4 rounded-xl ${verdictStyles.bg} border ${verdictStyles.border}`}>
                    <div className={`text-sm font-bold ${verdictStyles.text} mb-1`}>
                      Recommendation
                    </div>
                    <p className={`text-sm ${verdictStyles.text.replace("700", "600")}`}>
                      {insight.recommendation}
                    </p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
