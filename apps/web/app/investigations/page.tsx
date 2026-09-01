"use client";

import { useEffect, useState, useCallback } from "react";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { Investigation } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function InvestigationsPage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [wsId, setWsId] = useState("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!wsId) return;
    setLoading(true);
    try {
      const data = await apiFetch<Investigation[]>(`/api/investigations?workspace_id=${wsId}`);
      setInvestigations(data);
    } catch {}
    setLoading(false);
  }, [wsId]);

  useEffect(() => {
    const stored = localStorage.getItem("vedax_workspace_id") || "";
    setWsId(stored);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <AppLayout>
      <div className="p-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Investigation History</h1>
          <p className="text-text-muted text-sm mt-1">Review past investigations and their results</p>
        </div>

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : investigations.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No investigations yet</p>
            <p className="text-sm">Start an investigation from the workspace.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {investigations.map((inv) => (
              <div key={inv.id} className="bg-surface border border-border rounded-xl overflow-hidden">
                <button
                  onClick={() => setExpanded(expanded === inv.id ? null : inv.id)}
                  className="w-full text-left px-5 py-4 hover:bg-surface-2 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text truncate">{inv.question}</p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-text-muted">
                        <span>{inv.capabilities.join(", ") || "general"}</span>
                        <span>{inv.latency_ms}ms</span>
                        {inv.confidence != null && (
                          <span className={inv.confidence > 0.7 ? "text-success" : inv.confidence > 0.4 ? "text-warning" : "text-error"}>
                            {Math.round(inv.confidence * 100)}%
                          </span>
                        )}
                        <span>{formatDate(inv.created_at)}</span>
                      </div>
                    </div>
                    <span className="text-text-muted ml-4">{expanded === inv.id ? "^" : "v"}</span>
                  </div>
                </button>
                {expanded === inv.id && (
                  <div className="px-5 pb-4 border-t border-border pt-3">
                    <div className="text-sm text-text whitespace-pre-wrap mb-3">{inv.answer}</div>
                    {inv.citations.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-text-muted mb-1">Citations</h4>
                        <div className="space-y-1">
                          {inv.citations.map((c, i) => (
                            <div key={i} className="text-xs text-text-muted">
                              [{i + 1}] {c.document_name} p.{c.page || "?"}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
