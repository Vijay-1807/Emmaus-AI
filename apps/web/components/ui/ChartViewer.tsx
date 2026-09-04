"use client";

import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";
import { BarChart3, LineChart as LineIcon, AreaChart as AreaIcon, Table as TableIcon, Download } from "lucide-react";
import type { Chart as ChartType } from "@/lib/types";

interface ChartViewerProps {
  chart: ChartType;
}

const PALETTE = [
  "#6366f1", // Indigo
  "#10b981", // Emerald
  "#f59e0b", // Amber
  "#ec4899", // Pink
  "#06b6d4", // Cyan
  "#8b5cf6", // Purple
  "#f43f5e", // Rose
];

export default function ChartViewer({ chart }: ChartViewerProps) {
  const defaultMode = (chart.chart_type === "line" ? "line" : chart.chart_type === "pie" ? "pie" : "bar");
  const [viewType, setViewType] = useState<"bar" | "line" | "area" | "pie" | "table">(defaultMode);

  // Transform labels + series into Recharts data format: [{ label: 'Q1', series1: 10, series2: 20 }, ...]
  const chartData = useMemo(() => {
    if (!chart.labels || chart.labels.length === 0) return [];
    return chart.labels.map((label, idx) => {
      const row: Record<string, string | number> = { name: label };
      chart.series.forEach((s) => {
        row[s.name || "Value"] = s.values[idx] ?? 0;
      });
      return row;
    });
  }, [chart]);

  // Transform for Pie chart if needed
  const pieData = useMemo(() => {
    if (!chart.labels || chart.labels.length === 0) return [];
    const firstSeries = chart.series[0];
    if (!firstSeries) return [];
    return chart.labels.map((label, idx) => ({
      name: label,
      value: firstSeries.values[idx] ?? 0,
    }));
  }, [chart]);

  const seriesNames = useMemo(() => {
    return chart.series.map((s, idx) => s.name || `Series ${idx + 1}`);
  }, [chart]);

  const formatNumber = (val: number | string) => {
    if (typeof val !== "number") return val;
    if (Math.abs(val) >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
    if (Math.abs(val) >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
    return Number.isInteger(val) ? val.toString() : val.toFixed(2);
  };

  const handleExportCSV = () => {
    if (!chart.labels || chart.labels.length === 0) return;
    const header = [chart.x_label || "Label", ...seriesNames].join(",");
    const rows = chart.labels.map((label, idx) => {
      const vals = chart.series.map((s) => s.values[idx] ?? 0);
      return [`"${label}"`, ...vals].join(",");
    });
    const csvContent = "data:text/csv;charset=utf-8," + [header, ...rows].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${chart.title.replace(/[^a-z0-9]/gi, "_").toLowerCase() || "chart"}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="my-3 overflow-hidden rounded-2xl border border-black/[.08] bg-white/80 p-4 shadow-sm backdrop-blur-md transition hover:shadow-md">
      {/* Header */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-black/[.05] pb-2.5">
        <div>
          <h4 className="text-sm font-semibold tracking-tight text-[#1c1917]">{chart.title || "Data Visualization"}</h4>
          {chart.caption && <p className="text-xs text-[#78716c]">{chart.caption}</p>}
        </div>

        <div className="flex items-center gap-1 rounded-lg bg-black/[.04] p-0.5 text-xs">
          <button
            onClick={() => setViewType("bar")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 transition ${
              viewType === "bar" ? "bg-white font-medium text-black shadow-sm" : "text-[#78716c] hover:text-black"
            }`}
            title="Bar Chart"
          >
            <BarChart3 size={13} />
            <span className="hidden sm:inline">Bar</span>
          </button>
          <button
            onClick={() => setViewType("line")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 transition ${
              viewType === "line" ? "bg-white font-medium text-black shadow-sm" : "text-[#78716c] hover:text-black"
            }`}
            title="Line Chart"
          >
            <LineIcon size={13} />
            <span className="hidden sm:inline">Line</span>
          </button>
          <button
            onClick={() => setViewType("area")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 transition ${
              viewType === "area" ? "bg-white font-medium text-black shadow-sm" : "text-[#78716c] hover:text-black"
            }`}
            title="Area Chart"
          >
            <AreaIcon size={13} />
            <span className="hidden sm:inline">Area</span>
          </button>
          <button
            onClick={() => setViewType("table")}
            className={`flex items-center gap-1 rounded-md px-2 py-1 transition ${
              viewType === "table" ? "bg-white font-medium text-black shadow-sm" : "text-[#78716c] hover:text-black"
            }`}
            title="Data Table"
          >
            <TableIcon size={13} />
            <span className="hidden sm:inline">Table</span>
          </button>
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[#78716c] transition hover:text-black"
            title="Export CSV"
          >
            <Download size={13} />
          </button>
        </div>
      </div>

      {/* Chart Canvas or Table */}
      <div className="h-64 w-full pt-2">
        {viewType === "table" ? (
          <div className="h-full overflow-auto rounded-lg border border-black/[.05] bg-white text-xs">
            <table className="w-full text-left">
              <thead className="sticky top-0 border-b border-black/[.08] bg-[#fbf9f5] font-semibold text-[#44403c]">
                <tr>
                  <th className="px-3 py-2">{chart.x_label || "Category"}</th>
                  {seriesNames.map((name, i) => (
                    <th key={i} className="px-3 py-2 text-right">{name}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[.04]">
                {chart.labels.map((lbl, idx) => (
                  <tr key={idx} className="hover:bg-black/[.02]">
                    <td className="px-3 py-2 font-medium text-[#1c1917]">{lbl}</td>
                    {chart.series.map((s, si) => (
                      <td key={si} className="px-3 py-2 text-right text-[#57534e]">
                        {formatNumber(s.values[idx] ?? 0)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : viewType === "line" ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
              <XAxis dataKey="name" stroke="#a8a29e" fontSize={11} tickLine={false} />
              <YAxis stroke="#a8a29e" fontSize={11} tickLine={false} tickFormatter={formatNumber} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgba(255, 255, 255, 0.95)",
                  borderRadius: "12px",
                  border: "1px solid rgba(0,0,0,0.08)",
                  boxShadow: "0 8px 30px rgba(0,0,0,0.12)",
                  fontSize: "12px",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
              {seriesNames.map((name, idx) => (
                <Line
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stroke={PALETTE[idx % PALETTE.length]}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: PALETTE[idx % PALETTE.length] }}
                  activeDot={{ r: 6 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : viewType === "area" ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 5 }}>
              <defs>
                {seriesNames.map((name, idx) => {
                  const color = PALETTE[idx % PALETTE.length];
                  return (
                    <linearGradient key={name} id={`grad-${idx}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={color} stopOpacity={0.4} />
                      <stop offset="95%" stopColor={color} stopOpacity={0.0} />
                    </linearGradient>
                  );
                })}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
              <XAxis dataKey="name" stroke="#a8a29e" fontSize={11} tickLine={false} />
              <YAxis stroke="#a8a29e" fontSize={11} tickLine={false} tickFormatter={formatNumber} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgba(255, 255, 255, 0.95)",
                  borderRadius: "12px",
                  border: "1px solid rgba(0,0,0,0.08)",
                  fontSize: "12px",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
              {seriesNames.map((name, idx) => (
                <Area
                  key={name}
                  type="monotone"
                  dataKey={name}
                  stroke={PALETTE[idx % PALETTE.length]}
                  fill={`url(#grad-${idx})`}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        ) : viewType === "pie" ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgba(255, 255, 255, 0.95)",
                  borderRadius: "12px",
                  border: "1px solid rgba(0,0,0,0.08)",
                  fontSize: "12px",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "11px" }} />
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={80}
                innerRadius={45}
                paddingAngle={4}
              >
                {pieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={PALETTE[index % PALETTE.length]} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
              <XAxis dataKey="name" stroke="#a8a29e" fontSize={11} tickLine={false} />
              <YAxis stroke="#a8a29e" fontSize={11} tickLine={false} tickFormatter={formatNumber} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgba(255, 255, 255, 0.95)",
                  borderRadius: "12px",
                  border: "1px solid rgba(0,0,0,0.08)",
                  boxShadow: "0 8px 30px rgba(0,0,0,0.12)",
                  fontSize: "12px",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
              {seriesNames.map((name, idx) => (
                <Bar
                  key={name}
                  dataKey={name}
                  fill={PALETTE[idx % PALETTE.length]}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={48}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Axis Footer */}
      {(chart.x_label || chart.y_label) && viewType !== "table" && (
        <div className="mt-2 flex items-center justify-between text-[11px] text-[#a8a29e]">
          <span>{chart.x_label ? `X: ${chart.x_label}` : ""}</span>
          <span>{chart.y_label ? `Y: ${chart.y_label}` : ""}</span>
        </div>
      )}
    </div>
  );
}
