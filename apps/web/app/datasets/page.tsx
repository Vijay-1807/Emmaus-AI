"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import PageShell from "@/components/PageShell";
import { apiFetch, friendlyError } from "@/lib/api";
import { ensureWorkspaceId } from "@/lib/workspace";
import { useWorkspaceId } from "@/lib/useWorkspaceId";
import type { Dataset } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { BarChart2, Trash2, Upload, X, CheckSquare, Square, Info } from "lucide-react";

const STATUS_STYLE: Record<string, string> = {
  ready: "bg-emerald-500/15 text-emerald-700",
  processing: "bg-amber-500/15 text-amber-700",
  failed: "bg-red-500/15 text-red-700",
};

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const { wsId, setWsId } = useWorkspaceId();
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadDatasets = useCallback(async () => {
    // Aggregate every workspace so items never hide behind a stale selection.
    setLoading(true);
    try {
      const workspaces = await apiFetch<import("@/lib/types").Workspace[]>("/api/workspaces");
      const all: Dataset[] = [];
      for (const ws of workspaces) {
        try {
          const data = await apiFetch<Dataset[]>(`/api/datasets?workspace_id=${ws.id}`);
          all.push(...data);
        } catch { /* skip */ }
      }
      setDatasets(all);
    } catch (cause) {
      setError(friendlyError(cause).message);
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadDatasets(); }, [loadDatasets]);

  async function uploadFile(id: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    await apiFetch<Dataset>(`/api/datasets/upload?workspace_id=${id}`, { method: "POST", body: form });
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    // Upload button never dead-ends: create a workspace on the fly if needed.
    const id = await ensureWorkspaceId(wsId);
    if (!id) { setError("Could not prepare a workspace. Start one from Home."); return; }
    if (id !== wsId) setWsId(id);
    setUploading(true);
    setError("");
    try {
      await Promise.all(files.map((f) => uploadFile(id, f)));
      await loadDatasets();
    } catch (cause) {
      setError(friendlyError(cause).message);
    }
    setUploading(false);
  }

  async function handleDelete(id: string) {
    const target = datasets.find((d) => d.id === id);
    const wid = target?.workspace_id || wsId;
    if (!wid) return;
    try {
      await apiFetch(`/api/datasets/${id}?workspace_id=${wid}`, { method: "DELETE" });
      setDatasets((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
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
    if (!datasets.length || !confirm(`Delete all ${datasets.length} datasets? This cannot be undone.`)) return;
    setDeleting(true);
    await Promise.all(datasets.map((d) => handleDelete(d.id)));
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
    setSelected(selected.size === datasets.length ? new Set() : new Set(datasets.map((d) => d.id)));
  }

  return (
    <PageShell wide>
      {/* Header */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-editorial text-2xl font-medium italic tracking-tight">Datasets</h1>
            <button
              onClick={() => setShowInfo(!showInfo)}
              className="rounded-full p-1 text-[#8d8780] hover:bg-black/[.06] hover:text-black"
              title="How are datasets used?"
            >
              <Info size={15} />
            </button>
          </div>
          <p className="mt-1 text-sm text-[#655f59]">Upload CSV &amp; XLSX files for AI-powered data analysis and charting</p>
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
          {datasets.length > 0 && selected.size === 0 && (
            <button
              onClick={deleteAll}
              disabled={deleting}
              className="flex items-center gap-1.5 rounded-full border border-black/[.08] bg-white/60 px-3 py-1.5 text-xs font-medium text-[#655f59] backdrop-blur hover:bg-red-50 hover:border-red-200 hover:text-red-600 disabled:opacity-50"
            >
              <Trash2 size={12} />
              Clear all
            </button>
          )}
          <label className="flex cursor-pointer items-center gap-2 rounded-full bg-[#282521] px-4 py-2 text-sm font-medium text-white shadow-md transition hover:bg-black">
            <Upload size={14} />
            {uploading ? "Uploading…" : "Upload dataset"}
            <input ref={inputRef} type="file" className="hidden" multiple accept=".csv,.xlsx,.xls" onChange={handleUpload} />
          </label>
        </div>
      </div>

      {/* Info callout */}
      {showInfo && (
        <div className="mb-5 rounded-2xl border border-black/[.06] bg-white/60 p-4 text-sm text-[#24231f] backdrop-blur">
          <p className="font-semibold mb-1">How datasets work in Emmaus</p>
          <ul className="list-disc pl-4 space-y-1 text-xs leading-relaxed text-[#655f59]">
            <li><strong>Upload CSV or XLSX</strong> - The file is parsed and its rows/columns become available as structured data.</li>
            <li><strong>Ask in chat</strong> - Type queries like &quot;Show me a bar chart of sales by region&quot; or &quot;What is the average revenue per month?&quot; and the AI will analyse the dataset and render charts automatically.</li>
            <li><strong>Charts</strong> - Bar, Line, Area, and Pie charts render directly in the chat response.</li>
            <li><strong>Attach at query time</strong> - You can also drop a CSV directly in the home chat box for one-off analysis.</li>
          </ul>
          <button onClick={() => setShowInfo(false)} className="mt-3 text-xs text-[#6366f1] underline">Dismiss</button>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur">
          <X size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => { setError(""); void loadDatasets(); }} className="ml-auto shrink-0 rounded-full bg-[#282521] px-3 py-1 text-[11px] font-medium text-white transition hover:bg-black">Retry</button>
          <button onClick={() => setError("")} className="shrink-0 text-red-400 hover:text-red-600"><X size={12} /></button>
        </div>
      )}



      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1,2,3].map((i) => <div key={i} className="h-32 animate-pulse rounded-2xl bg-white/50" />)}
        </div>
      ) : datasets.length === 0 ? (
        <div className="rounded-2xl border border-black/[.06] bg-white/50 py-16 text-center backdrop-blur">
          <BarChart2 size={32} className="mx-auto mb-3 text-[#8d8780]/50" />
          <p className="text-sm font-medium text-[#655f59]">No datasets yet</p>
          <p className="mt-1 text-xs text-[#8d8780]">Upload a CSV or XLSX to start analysing data in chat</p>
        </div>
      ) : (
        <>
          {/* Bulk select bar */}
          <div className="mb-3 flex items-center gap-3">
            <button onClick={toggleAll} className="flex items-center gap-1.5 text-xs text-[#655f59] hover:text-black">
              {selected.size === datasets.length && datasets.length > 0 ? (
                <CheckSquare size={14} className="text-[#6366f1]" />
              ) : <Square size={14} />}
              {selected.size === datasets.length && datasets.length > 0 ? "Deselect all" : "Select all"}
            </button>
            <span className="text-xs text-[#8d8780]">{datasets.length} dataset{datasets.length !== 1 ? "s" : ""}</span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {datasets.map((ds) => (
              <div
                key={ds.id}
                className={`relative rounded-2xl border p-5 backdrop-blur transition ${selected.has(ds.id) ? "border-[#6366f1]/40 bg-[#6366f1]/[.07] shadow-sm" : "border-black/[.06] bg-white/60 shadow-sm hover:bg-white/75"}`}
              >
                {/* Checkbox */}
                <button
                  onClick={() => toggleSelect(ds.id)}
                  className="absolute left-3.5 top-3.5"
                >
                  {selected.has(ds.id)
                    ? <CheckSquare size={15} className="text-[#6366f1]" />
                    : <Square size={15} className="text-[#8d8780]/50 hover:text-[#655f59]" />}
                </button>

                {/* Delete X */}
                <button
                  onClick={() => handleDelete(ds.id)}
                  className="absolute right-3 top-3 rounded-lg p-1 text-[#8d8780]/60 transition hover:bg-red-50 hover:text-red-500"
                  title="Delete"
                >
                  <X size={13} />
                </button>

                <div className="pl-5 pr-5">
                  <div className="flex items-center gap-2 mb-2">
                    <BarChart2 size={16} className="shrink-0 text-[#6366f1]" />
                    <h3 className="truncate text-sm font-semibold text-[#24231f]">{ds.filename}</h3>
                  </div>

                  <div className="space-y-1 text-xs text-[#655f59]">
                    <p>{ds.num_rows?.toLocaleString() ?? "?"} rows · {ds.columns.length} columns</p>
                    <p className="text-[11px] text-[#8d8780]">{formatDate(ds.created_at)}</p>
                  </div>

                  <span className={`mt-2 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[ds.status] ?? "bg-black/[.06] text-[#655f59]"}`}>
                    {ds.status === "processing" && <span className="mr-1 h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />}
                    {ds.status}
                  </span>

                  {ds.columns.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1">
                      {ds.columns.slice(0, 5).map((col) => (
                        <span key={col.name} className="rounded-full bg-black/[.05] px-2 py-0.5 text-[10px] text-[#655f59]">
                          {col.name}
                        </span>
                      ))}
                      {ds.columns.length > 5 && (
                        <span className="text-[10px] text-[#8d8780]">+{ds.columns.length - 5} more</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </PageShell>
  );
}
