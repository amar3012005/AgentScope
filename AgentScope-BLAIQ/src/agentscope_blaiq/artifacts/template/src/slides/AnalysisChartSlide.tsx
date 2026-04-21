import React from "react";

interface ChartPoint {
  label: string;
  value: number;
  value2?: number;
  label2?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  chartType: "line" | "bar" | "area";
  data: ChartPoint[];
  chartTitle?: string;
  yLabel?: string;
  showGrid?: boolean;
  index: number;
  total?: number;
}

export function AnalysisChartSlide({
  title,
  subtitle,
  chartType = "line",
  data,
  chartTitle,
  yLabel,
  showGrid = true,
}: Props): JSX.Element {
  // Calculate chart dimensions and scales
  const width = 800;
  const height = 300;
  const padding = { top: 20, right: 20, bottom: 50, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const allValues = data.flatMap((d) => [d.value, ...(d.value2 !== undefined ? [d.value2] : [])]);
  const maxValue = Math.max(...allValues);
  const minValue = Math.min(...allValues);
  const yMax = Math.ceil(maxValue * 1.1);

  const xScale = chartWidth / (data.length - 1);
  const yScale = chartHeight / (yMax - minValue);

  const getY = (value: number) => chartHeight - (value - minValue) * yScale;
  const getX = (index: number) => index * xScale;

  // Generate path for line chart
  const linePath = data
    .map((d, i) => `${i === 0 ? "M" : "L"} ${getX(i)} ${getY(d.value)}`)
    .join(" ");

  // Generate path for area fill
  const areaPath = `${linePath} L ${chartWidth} ${chartHeight} L 0 ${chartHeight} Z`;

  // Generate second line if value2 exists
  const linePath2 =
    data[0]?.value2 !== undefined
      ? data.map((d, i) => `${i === 0 ? "M" : "L"} ${getX(i)} ${getY(d.value2!)}`).join(" ")
      : null;

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

      {/* Chart Card */}
      <div
        className="relative z-10 bg-white rounded-3xl p-8 shadow-[0_4px_24px_rgba(0,0,0,0.06)]"
        style={{
          opacity: 0,
          animation: `slideUp 0.8s ease-out 0.2s forwards`,
        }}
      >
        {chartTitle && (
          <h3 className="text-lg font-semibold text-[#334155] mb-6">{chartTitle}</h3>
        )}

        {/* SVG Chart */}
        <div className="w-full overflow-x-auto">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-auto"
            style={{ minHeight: "300px" }}
          >
            {/* Grid lines */}
            {showGrid &&
              [0, 0.25, 0.5, 0.75, 1].map((ratio, i) => (
                <g key={i}>
                  <line
                    x1={padding.left}
                    y1={padding.top + ratio * chartHeight}
                    x2={padding.left + chartWidth}
                    y2={padding.top + ratio * chartHeight}
                    stroke="#e2e8f0"
                    strokeWidth="1"
                    strokeDasharray={i === 0 ? "" : "4 4"}
                  />
                  <text
                    x={padding.left - 12}
                    y={padding.top + ratio * chartHeight + 4}
                    textAnchor="end"
                    className="text-xs fill-[#64748b]"
                    style={{ fontSize: "12px" }}
                  >
                    {Math.round(yMax - ratio * (yMax - minValue))}
                  </text>
                </g>
              ))}

            {/* Y-axis label */}
            {yLabel && (
              <text
                x={16}
                y={padding.top + chartHeight / 2}
                textAnchor="middle"
                className="text-sm fill-[#64748b]"
                style={{ fontSize: "11px" }}
                transform={`rotate(-90, 16, ${padding.top + chartHeight / 2})`}
              >
                {yLabel}
              </text>
            )}

            {/* X-axis labels */}
            {data.map((d, i) => (
              <text
                key={i}
                x={padding.left + getX(i)}
                y={height - 15}
                textAnchor="middle"
                className="text-xs fill-[#64748b]"
                style={{ fontSize: "11px" }}
              >
                {d.label}
              </text>
            ))}

            {/* Area fill (for area charts) */}
            {chartType === "area" && (
              <path
                d={areaPath}
                transform={`translate(${padding.left}, ${padding.top})`}
                fill="url(#areaGradient)"
                opacity="0.3"
              />
            )}

            {/* Main line */}
            <path
              d={linePath}
              transform={`translate(${padding.left}, ${padding.top})`}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Second line if exists */}
            {linePath2 && (
              <>
                <path
                  d={linePath2}
                  transform={`translate(${padding.left}, ${padding.top})`}
                  fill="none"
                  stroke="#8b5cf6"
                  strokeWidth="3"
                  strokeDasharray="6 4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {data[0]?.label2 && (
                  <text
                    x={width - 100}
                    y={padding.top + 30}
                    className="text-sm fill-[#8b5cf6]"
                    style={{ fontSize: "12px", fontWeight: 600 }}
                  >
                    {data[0].label2}
                  </text>
                )}
              </>
            )}

            {/* Data points */}
            {data.map((d, i) => (
              <g key={i}>
                <circle
                  cx={padding.left + getX(i)}
                  cy={padding.top + getY(d.value)}
                  r="6"
                  fill="#3b82f6"
                  stroke="#fff"
                  strokeWidth="3"
                />
                {d.value2 !== undefined && (
                  <circle
                    cx={padding.left + getX(i)}
                    cy={padding.top + getY(d.value2)}
                    r="6"
                    fill="#8b5cf6"
                    stroke="#fff"
                    strokeWidth="3"
                  />
                )}
              </g>
            ))}

            {/* Gradient definition */}
            <defs>
              <linearGradient id="areaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#3b82f6" />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
        </div>

        {/* Legend */}
        <div className="flex items-center justify-center gap-8 mt-6">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-[#3b82f6]" />
            <span className="text-sm text-[#64748b]">Primary</span>
          </div>
          {data[0]?.value2 !== undefined && (
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-[#8b5cf6]" />
              <span className="text-sm text-[#64748b]">{data[0].label2 || "Secondary"}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
