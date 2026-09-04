"use client";

import { useEffect, useState, useCallback } from "react";
import PageShell from "@/components/PageShell";
import { apiFetch } from "@/lib/api";
import { clearStoredWorkspaceIdIf, isNotFoundError } from "@/lib/workspace";
import { useWorkspaceId } from "@/lib/useWorkspaceId";
import type { Investigation } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Clock, CheckSquare, Square, Trash2, ChevronDown, ChevronUp, X } from "lucide-react";

export default function InvestigationsPage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const { wsId, setWsId } = useWorkspaceId();
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!wsId) { setLoading(false); return; }
    setLoading(true);
    try {
      const data = await apiFetch<Investigation[]>(`/api/investigations?workspace_id=${wsId}`);
      setInvestigations(data);
    } catch (cause) {
      if (isNotFoundError(cause)) {
        clearStoredWorkspaceIdIf(wsId);
        setWsId("");
        setInvestigations([]);
      } else {
        setError("Failed to load history.");
      }
    }
    setLoading(false);
  }, [wsId, setWsId]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id: string) {
    try {
      await apiFetch(`/api/investigations/${id}?workspace_id=${wsId}`, { method: "DELETE" });
      setInvestigations((prev) => prev.filter((i) => i.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
      if (expanded === id) setExpanded(null);
    } catch { setError("Delete failed."); }
  }

  async function deleteSelected() {
    if (!selected.size) return;
    setDeleting(true);
    await Promise.all([...selected].map(handleDelete));
    setSelected(new Set());
    setDeleting(false);
  }

  async function deleteAll() {
    if (!investigations.length || !confirm(`Clear all ${investigations.length} investigations? This cannot be undone.`)) return;
    setDeleting(true);
    await Promise.all(investigations.map((inv) => handleDelete(inv.id)));
    setDeleting(false);
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  function toggleAll() {
    setSelected(selected.size === investigations.length ? new Set() : new Set(investigations.map((i) => i.id)));
  }

  const confidenceColor = (c: number) =>
    c > 0.7 ? "text-emerald-600" : c > 0.4 ? "text-amber-600" : "text-red-500";

  return (
    <PageShell>
      {/* Header */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Investigation History</h1>
          <p className="mt-1 text-sm text-[#655f59]">Review past investigations and expand to read answers</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={deleteSelected}
              disabled={deleting}
              className="flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50/80 px-3 py-1.5 text-xs font-medium text-red-600 backdrop-blur hover:bg-red-100 disabled:opacity-50"
            >
              <Trash2 size={12} />
              Delete {selected.size} selected
            </button>
          )}
          {investigations.length > 0 && selected.size === 0 && (
            <button
              type="button"
              onClick={deleteAll}
              disabled={deleting}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-black/[.08] bg-white/60 text-[#655f59] backdrop-blur hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
              title="Clear all investigations"
              aria-label="Clear all"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur">
          <span>{error}</span>
          <button onClick={() => setError("")} className="ml-auto shrink-0 text-red-400 hover:text-red-600"><X size={12} /></button>
        </div>
      )}



      {!wsId && !loading && (
        <div className="mb-4 rounded-2xl border border-amber-200/60 bg-amber-50/80 px-4 py-3 text-sm text-amber-800 backdrop-blur">
          No workspace selected. Start an investigation from Home first, then review history here.
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[1,2,3].map((i) => <div key={i} className="h-16 animate-pulse rounded-2xl bg-white/50" />)}
        </div>
      ) : investigations.length === 0 ? (
        <div className="rounded-2xl border border-black/[.06] bg-white/50 py-16 text-center backdrop-blur">
          <Clock size={32} className="mx-auto mb-3 text-[#8d8780]/50" />
          <p className="text-sm font-medium text-[#655f59]">No investigations yet</p>
          <p className="mt-1 text-xs text-[#8d8780]">Start an investigation from Home to see history here.</p>
        </div>
      ) : (
        <>
          {/* Bulk select bar */}
          <div className="mb-3 flex items-center gap-3">
            <button onClick={toggleAll} className="flex items-center gap-1.5 text-xs text-[#655f59] hover:text-black">
              {selected.size === investigations.length && investigations.length > 0
                ? <CheckSquare size={14} className="text-[#6366f1]" />
                : <Square size={14} />}
              {selected.size === investigations.length && investigations.length > 0 ? "Deselect all" : "Select all"}
            </button>
            <span className="text-xs text-[#8d8780]">{investigations.length} investigation{investigations.length !== 1 ? "s" : ""}</span>
          </div>

          <div className="space-y-2">
            {investigations.map((inv) => (
              <div
                key={inv.id}
                className={`overflow-hidden rounded-2xl border backdrop-blur transition ${selected.has(inv.id) ? "border-[#6366f1]/40 bg-[#6366f1]/[.07]" : "border-black/[.06] bg-white/60 shadow-sm"}`}
              >
                <div className="flex items-center gap-3 px-4 py-3">
                  {/* Checkbox */}
                  <button onClick={() => toggleSelect(inv.id)} className="shrink-0">
                    {selected.has(inv.id)
                      ? <CheckSquare size={15} className="text-[#6366f1]" />
                      : <Square size={15} className="text-[#8d8780]/50 hover:text-[#655f59]" />}
                  </button>

                  {/* Expand toggle */}
                  <button
                    onClick={() => setExpanded(expanded === inv.id ? null : inv.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-medium text-[#24231f]">{inv.question}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[#8d8780]">
                      {inv.capabilities?.length > 0 && (
                        <span className="rounded-full bg-black/[.05] px-1.5 py-0.5 text-[10px]">
                          {inv.capabilities.join(", ")}
                        </span>
                      )}
                      {inv.latency_ms != null && <span>{inv.latency_ms}ms</span>}
                      {inv.confidence != null && (
                        <span className={`font-medium ${confidenceColor(inv.confidence)}`}>
                          {Math.round(inv.confidence * 100)}% confidence
                        </span>
                      )}
                      <span>{formatDate(inv.created_at)}</span>
                    </div>
                  </button>

                  {/* Chevron + delete */}
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() => setExpanded(expanded === inv.id ? null : inv.id)}
                      className="rounded-lg p-1.5 text-[#8d8780] hover:bg-black/[.06] hover:text-black"
                    >
                      {expanded === inv.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                    <button
                      onClick={() => handleDelete(inv.id)}
                      className="rounded-lg p-1.5 text-[#8d8780]/60 hover:bg-red-50 hover:text-red-500"
                      title="Delete"
                    >
                      <X size={13} />
                    </button>
                  </div>
                </div>

                {/* Expanded answer */}
                {expanded === inv.id && (
                  <div className="border-t border-black/[.06] bg-white/50 px-5 pb-5 pt-4">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#514c47]">{inv.answer}</p>
                    {inv.citations?.length > 0 && (
                      <div className="mt-4">
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#8d8780]">Citations</p>
                        <div className="space-y-1">
                          {inv.citations.map((c, i) => (
                            <div key={i} className="flex items-start gap-2 text-xs text-[#655f59]">
                              <span className="shrink-0 rounded bg-black/[.07] px-1.5 py-0.5 text-[10px] font-bold text-[#514c47]">[{i + 1}]</span>
                              <span>{c.document_name}{c.page != null ? ` · p.${c.page}` : ""}</span>
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
        </>
      )}
    </PageShell>
  );
}
