import React from "react";

interface TableRow {
  [key: string]: string | number | undefined;
  label?: string;
}

interface Column {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  format?: "number" | "currency" | "percentage" | "text";
  highlight?: "positive" | "negative" | "neutral";
}

interface Props {
  title: string;
  subtitle?: string;
  columns: Column[];
  data: TableRow[];
  highlightColumn?: string;
  index: number;
  total?: number;
}

export function DataTableSlide({
  title,
  subtitle,
  columns,
  data,
  highlightColumn,
}: Props): JSX.Element {
  const formatValue = (value: string | number | undefined, format?: string) => {
    if (value === undefined) return "-";
    if (typeof value === "number") {
      if (format === "currency") return `$${value.toLocaleString()}`;
      if (format === "percentage") return `${value}%`;
      if (format === "number") return value.toLocaleString();
    }
    return String(value);
  };

  const getCellValueStyle = (value: string | number | undefined, highlight?: string) => {
    const base = "font-medium";
    if (highlight === "positive") return `${base} text-emerald-700`;
    if (highlight === "negative") return `${base} text-red-700`;
    return `${base} text-[#334155]`;
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

      {/* Table Card */}
      <div
        className="relative z-10 bg-white rounded-3xl shadow-[0_4px_24px_rgba(0,0,0,0.06)] overflow-hidden"
        style={{
          opacity: 0,
          animation: `slideUp 0.8s ease-out 0.2s forwards`,
        }}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gradient-to-r from-[#3b82f6] to-[#8b5cf6]">
                {columns.map((col, i) => (
                  <th
                    key={i}
                    className={`px-6 py-5 text-left text-sm font-bold uppercase tracking-wider text-white ${
                      col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"
                    }`}
                  >
                    {col.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, rowIndex) => (
                <tr
                  key={rowIndex}
                  className={`border-b border-[#e2e8f0] transition-colors ${
                    rowIndex % 2 === 0 ? "bg-white" : "bg-[#f8fafc]"
                  } hover:bg-[#f1f5f9]`}
                  style={{
                    opacity: 0,
                    animation: `slideRight 0.5s ease-out ${0.1 + rowIndex * 0.08}s forwards`,
                  }}
                >
                  {columns.map((col, colIndex) => {
                    const value = row[col.key];
                    const isHighlighted = highlightColumn && col.key === highlightColumn;
                    return (
                      <td
                        key={colIndex}
                        className={`px-6 py-5 text-sm ${
                          isHighlighted ? "font-bold text-[#0f172a]" : getCellValueStyle(value, col.highlight)
                        } ${
                          col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"
                        }`}
                      >
                        {formatValue(value, col.format)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Table footer with row count */}
        <div className="px-6 py-4 bg-[#f8fafc] border-t border-[#e2e8f0]">
          <span className="text-xs text-[#64748b] font-medium">
            {data.length} {data.length === 1 ? "row" : "rows"}
          </span>
        </div>
      </div>
    </section>
  );
}
