"use client";

import { useEffect, useState, useCallback } from "react";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { EvalRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function EvaluationPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [wsId, setWsId] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const loadRuns = useCallback(async () => {
    if (!wsId) return;
    setLoading(true);
    try {
      const data = await apiFetch<EvalRun[]>(`/api/evaluation/runs?workspace_id=${wsId}`);
      setRuns(data);
    } catch {}
    setLoading(false);
  }, [wsId]);

  useEffect(() => {
    const stored = localStorage.getItem("vedax_workspace_id") || "";
    setWsId(stored);
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  async function startRun() {
    if (!wsId || running) return;
    setRunning(true);
    try {
      await apiFetch("/api/evaluation/runs", {
        method: "POST",
        body: JSON.stringify({ workspace_id: wsId, retrieval_mode: "hybrid_rerank" }),
      });
      await loadRuns();
    } catch {}
    setRunning(false);
  }

  function metric(val: number | null, pct = false) {
    if (val == null) return <span className="text-text-muted">--</span>;
    return <span className={val > 0.7 ? "text-success" : val > 0.4 ? "text-warning" : "text-error"}>{pct ? `${Math.round(val * 100)}%` : val.toFixed(4)}</span>;
  }

  return (
    <AppLayout>
      <div className="p-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Evaluation</h1>
            <p className="text-text-muted text-sm mt-1">RAG and agent benchmark results</p>
          </div>
          <button
            onClick={startRun}
            disabled={running}
            className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-hover transition-colors disabled:opacity-50"
          >
            {running ? "Running..." : "Run evaluation"}
          </button>
        </div>

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : runs.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No evaluation runs yet</p>
            <p className="text-sm">Seed evaluation cases and run benchmarks.</p>
          </div>
        ) : (
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Cases</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Recall@5</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">MRR</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Correctness</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Faithfulness</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Citation</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Latency</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-border hover:bg-surface-2 transition-colors">
                    <td className={`px-4 py-3 text-xs font-medium ${run.status === "completed" ? "text-success" : run.status === "failed" ? "text-error" : "text-warning"}`}>
                      {run.status}
                    </td>
                    <td className="px-4 py-3 text-text-muted">{run.num_cases}</td>
                    <td className="px-4 py-3">{metric(run.retrieval_recall_at_5, true)}</td>
                    <td className="px-4 py-3">{metric(run.retrieval_mrr)}</td>
                    <td className="px-4 py-3">{metric(run.answer_correctness, true)}</td>
                    <td className="px-4 py-3">{metric(run.faithfulness, true)}</td>
                    <td className="px-4 py-3">{metric(run.citation_accuracy, true)}</td>
                    <td className="px-4 py-3 text-text-muted">{run.avg_latency_ms ? `${Math.round(run.avg_latency_ms)}ms` : "--"}</td>
                    <td className="px-4 py-3 text-text-muted text-xs">{formatDate(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
