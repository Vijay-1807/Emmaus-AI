"use client";

import { useEffect, useState, useCallback, useRef, Fragment } from "react";
import { apiFetch } from "@/lib/api";
import type { EvalRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function Metric({ value, pct = false }: { value: number | null; pct?: boolean }) {
  if (value == null) return <span className="text-[#8d8780]">--</span>;
  const cls = value > 0.7 ? "text-emerald-600" : value > 0.4 ? "text-amber-600" : "text-red-500";
  return <span className={cls}>{pct ? `${Math.round(value * 100)}%` : value.toFixed(4)}</span>;
}

export default function EvaluationPanel({ workspaceId }: { workspaceId: string }) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [caseCount, setCaseCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canRun = (caseCount ?? 0) > 0;

  async function seedFromHistory() {
    if (!workspaceId || seeding) return;
    setSeeding(true);
    setError("");
    try {
      await apiFetch<{ inserted: number }>("/api/evaluation/seed-from-history", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, limit: 10 }),
      });
      await loadCases();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Seeding failed.");
    } finally {
      setSeeding(false);
    }
  }

  const loadRuns = useCallback(async () => {
    if (!workspaceId) { setLoading(false); return; }
    try {
      const data = await apiFetch<EvalRun[]>(`/api/evaluation/runs?workspace_id=${workspaceId}`);
      setRuns(data);
      setError("");
      return data;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load evaluation runs.");
      return [];
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  const loadCases = useCallback(async () => {
    if (!workspaceId) return;
    try {
      // Total count isn't exposed; list length (capped at 200) is the indicator.
      const all = await apiFetch<unknown[]>(`/api/evaluation/cases?limit=200`);
      setCaseCount(all.length);
    } catch {
      setCaseCount(null);
    }
  }, [workspaceId]);

  useEffect(() => {
    setLoading(true);
    void loadRuns();
    void loadCases();
  }, [loadRuns, loadCases]);

  // Poll while any run is still executing.
  useEffect(() => {
    if (runs.some((r) => r.status === "running")) {
      pollTimer.current = setTimeout(() => { void loadRuns(); }, 4000);
    }
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [runs, loadRuns]);

  async function startRun() {
    if (!workspaceId || running || !canRun) return;
    setRunning(true);
    setError("");
    try {
      await apiFetch("/api/evaluation/run", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, retrieval_mode: "hybrid_rerank" }),
      });
      await loadRuns();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to start evaluation.");
    } finally {
      setRunning(false);
    }
  }

  if (!workspaceId) {
    return (
      <div>
        <h3 className="mb-3 text-base font-semibold">Evaluation</h3>
        <div className="rounded-2xl border border-amber-200/60 bg-amber-50/80 px-4 py-3 text-sm text-amber-800 backdrop-blur">
          No workspace selected. Start an investigation from Home first.
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-semibold">RAG &amp; agent benchmarks</h3>
          <p className="mt-0.5 text-xs text-[#655f59]">
            {caseCount == null ? "Seeded cases unknown" : `${caseCount} seeded case${caseCount !== 1 ? "s" : ""}`} · hybrid_rerank pipeline
          </p>
        </div>
        <button
          onClick={startRun}
          disabled={running || !canRun}
          title={!canRun ? "Seed at least one case first" : "Run benchmark"}
          className="shrink-0 rounded-full bg-[#282521] px-4 py-2 text-xs font-semibold text-white shadow-md transition hover:bg-black disabled:opacity-50"
        >
          {running ? "Starting…" : "Run evaluation"}
        </button>
      </div>

      {!loading && caseCount === 0 && (
        <div className="mb-4 rounded-2xl border border-amber-200/60 bg-amber-50/80 px-4 py-3 text-xs leading-relaxed text-amber-800 backdrop-blur">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p>
              <span className="font-semibold">No seeded cases yet</span> — turn your
              recent chats into benchmark cases in one click, then run.
            </p>
            <button
              onClick={seedFromHistory}
              disabled={seeding}
              className="shrink-0 rounded-full bg-[#282521] px-4 py-2 text-[11px] font-semibold text-white shadow-md transition hover:bg-black disabled:opacity-50"
            >
              {seeding ? "Seeding…" : "Seed from recent chats"}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-2xl border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-white/50" />)}
        </div>
      ) : runs.length === 0 ? (
        <div className="rounded-2xl border border-black/[.06] bg-white/50 py-12 text-center backdrop-blur">
          <p className="text-sm font-medium text-[#655f59]">No evaluation runs yet</p>
          <p className="mt-1 text-xs text-[#8d8780]">Run a benchmark to measure recall, correctness, faithfulness, and citation accuracy.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-black/[.06] bg-white/60 shadow-sm backdrop-blur">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-black/[.06]">
                  {["Status", "Cases", "Recall@5", "MRR", "Correct", "Faithful", "Citation", "Latency", "Date"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-[#6a635d]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <Fragment key={run.id}>
                    <tr
                      onClick={() => setExpanded(expanded === run.id ? null : run.id)}
                      title={run.status === "failed" && run.error ? run.error : "Click for run details"}
                      className="cursor-pointer border-b border-black/[.04] transition last:border-0 hover:bg-white/60"
                    >
                      <td className={`px-4 py-3 text-xs font-medium ${run.status === "completed" ? "text-emerald-600" : run.status === "failed" ? "text-red-500" : "text-amber-600"}`}>
                        {run.status === "running" && <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />}
                        {run.status}
                      </td>
                      <td className="px-4 py-3 text-[#655f59]">{run.num_cases}</td>
                      <td className="px-4 py-3"><Metric value={run.retrieval_recall_at_5} pct /></td>
                      <td className="px-4 py-3"><Metric value={run.retrieval_mrr} /></td>
                      <td className="px-4 py-3"><Metric value={run.answer_correctness} pct /></td>
                      <td className="px-4 py-3"><Metric value={run.faithfulness} pct /></td>
                      <td className="px-4 py-3"><Metric value={run.citation_accuracy} pct /></td>
                      <td className="px-4 py-3 text-[#655f59]">{run.avg_latency_ms ? `${Math.round(run.avg_latency_ms)}ms` : "--"}</td>
                      <td className="px-4 py-3 text-xs text-[#8d8780]">{formatDate(run.created_at)}</td>
                    </tr>
                    {expanded === run.id && (
                      <tr className="border-b border-black/[.04] bg-black/[.02] last:border-0">
                        <td colSpan={9} className="px-4 py-3 text-xs">
                          <span className="font-mono text-[#8d8780]">
                            mode: {run.config?.retrieval_mode ?? "hybrid_rerank"}
                          </span>
                          {run.error && (
                            <p className="mt-1 font-medium text-red-600">{run.error}</p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
