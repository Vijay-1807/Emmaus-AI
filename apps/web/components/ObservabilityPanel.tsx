"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import type { ObservabilitySummary, TraceRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-black/[.06] bg-white/60 p-3 backdrop-blur">
      <div className="text-[11px] text-[#8d8780]">{label}</div>
      <div className="mt-0.5 text-base font-bold">{value}</div>
      {sub && <div className="text-[10px] text-[#8d8780]">{sub}</div>}
    </div>
  );
}

export default function ObservabilityPanel({ workspaceId }: { workspaceId: string }) {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [traces, setTraces] = useState<TraceRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!workspaceId) { setLoading(false); return; }
    setLoading(true);
    try {
      const [s, t] = await Promise.all([
        apiFetch<ObservabilitySummary>(`/api/observability/summary?workspace_id=${workspaceId}`),
        apiFetch<TraceRun[]>(`/api/observability/traces?workspace_id=${workspaceId}`),
      ]);
      setSummary(s);
      setTraces(t);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load observability data.");
    }
    setLoading(false);
  }, [workspaceId]);

  useEffect(() => { void load(); }, [load]);

  if (!workspaceId) {
    return (
      <div>
        <h3 className="mb-3 text-base font-semibold">Observability</h3>
        <div className="rounded-2xl border border-amber-200/60 bg-amber-50/80 px-4 py-3 text-sm text-amber-800 backdrop-blur">
          No workspace selected. Start an investigation from Home first.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-white/50" />)}
        </div>
        <div className="h-24 animate-pulse rounded-2xl bg-white/50" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur">
        {error}{" "}
        <button onClick={() => void load()} className="underline">Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Investigations" value={String(summary?.total_investigations ?? 0)} />
        <Stat
          label="Avg latency"
          value={summary?.avg_latency_ms ? `${Math.round(summary.avg_latency_ms)}ms` : "--"}
          sub={summary ? `p50 ${Math.round(summary.p50_latency_ms)}ms · p95 ${Math.round(summary.p95_latency_ms)}ms` : undefined}
        />
        <Stat label="Total tokens" value={(summary?.total_tokens ?? 0).toLocaleString()} sub={summary ? `≈ $${summary.estimated_cost_usd.toFixed(4)}` : undefined} />
        <Stat
          label="Fallback rate"
          value={summary ? `${Math.round(summary.fallback_rate * 100)}%` : "--"}
          sub={summary ? `error rate ${Math.round(summary.error_rate * 100)}%` : undefined}
        />
      </div>

      {/* Provider usage */}
      {summary && summary.provider_usage.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#6a635d]">Provider usage</h4>
          <div className="overflow-hidden rounded-2xl border border-black/[.06] bg-white/60 backdrop-blur">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-black/[.06]">
                    {["Provider", "Model", "Calls", "Tokens", "Avg latency"].map((h) => (
                      <th key={h} className="px-4 py-2.5 text-left text-xs font-medium text-[#6a635d]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {summary.provider_usage.map((p, i) => (
                    <tr key={i} className="border-b border-black/[.04] last:border-0">
                      <td className="px-4 py-2.5 font-medium">{p.provider}</td>
                      <td className="px-4 py-2.5 font-mono text-xs text-[#655f59]">{p.model}</td>
                      <td className="px-4 py-2.5 text-[#655f59]">{p.calls}</td>
                      <td className="px-4 py-2.5 text-[#655f59]">{p.tokens.toLocaleString()}</td>
                      <td className="px-4 py-2.5 text-[#655f59]">{Math.round(p.avg_latency_ms)}ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Recent traces */}
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-[#6a635d]">Recent traces</h4>
        {traces.length === 0 ? (
          <div className="rounded-2xl border border-black/[.06] bg-white/50 py-10 text-center backdrop-blur">
            <p className="text-sm font-medium text-[#655f59]">No traces yet</p>
            <p className="mt-1 text-xs text-[#8d8780]">Traces appear after running investigations.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {traces.slice(0, 20).map((t) => (
              <div key={t.id} className="rounded-2xl border border-black/[.06] bg-white/60 px-4 py-3 backdrop-blur">
                <p className="truncate text-sm font-medium" title={t.question}>{t.question || "(untitled investigation)"}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[#8d8780]">
                  {t.status && (
                    <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${t.status === "completed" ? "bg-emerald-500/15 text-emerald-700" : "bg-amber-500/15 text-amber-700"}`}>
                      {t.status}
                    </span>
                  )}
                  {t.capabilities?.length > 0 && (
                    <span className="rounded-full bg-black/[.05] px-1.5 py-0.5 text-[10px]">{t.capabilities.join(", ")}</span>
                  )}
                  <span>{t.model_run_count} model runs</span>
                  <span>{t.tool_run_count} tool calls</span>
                  {t.latency_ms != null && <span>{Math.round(t.latency_ms)}ms</span>}
                  {t.confidence != null && <span className="font-medium text-emerald-600">{Math.round(t.confidence * 100)}%</span>}
                  <span>{formatDate(t.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
