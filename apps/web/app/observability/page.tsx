"use client";

import { useEffect, useState, useCallback } from "react";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { TraceRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function ObservabilityPage() {
  const [traces, setTraces] = useState<TraceRun[]>([]);
  const [wsId, setWsId] = useState("");
  const [loading, setLoading] = useState(true);

  const loadTraces = useCallback(async () => {
    if (!wsId) return;
    setLoading(true);
    try {
      const data = await apiFetch<TraceRun[]>(`/api/observability/traces?workspace_id=${wsId}`);
      setTraces(data);
    } catch {}
    setLoading(false);
  }, [wsId]);

  useEffect(() => {
    const stored = localStorage.getItem("vedax_workspace_id") || "";
    setWsId(stored);
  }, []);

  useEffect(() => { loadTraces(); }, [loadTraces]);

  return (
    <AppLayout>
      <div className="p-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Observability</h1>
          <p className="text-text-muted text-sm mt-1">Model runs, traces, and performance metrics</p>
        </div>

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : traces.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No traces yet</p>
            <p className="text-sm">Traces appear after running investigations.</p>
          </div>
        ) : (
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Provider</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Model</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Task</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Latency</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Input Tokens</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Output Tokens</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {traces.map((t) => (
                  <tr key={t.id} className="border-b border-border hover:bg-surface-2 transition-colors">
                    <td className="px-4 py-3 text-text">{t.provider}</td>
                    <td className="px-4 py-3 text-text-muted">{t.model}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 bg-bg border border-border rounded text-xs text-text-muted">{t.task}</span>
                    </td>
                    <td className="px-4 py-3 text-text-muted">{Math.round(t.latency_ms)}ms</td>
                    <td className="px-4 py-3 text-text-muted">{t.input_tokens}</td>
                    <td className="px-4 py-3 text-text-muted">{t.output_tokens}</td>
                    <td className="px-4 py-3 text-text-muted text-xs">{formatDate(t.created_at)}</td>
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
