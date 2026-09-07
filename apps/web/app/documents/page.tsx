"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import PageShell from "@/components/PageShell";
import { apiFetch, friendlyError } from "@/lib/api";
import { clearStoredWorkspaceIdIf, ensureWorkspaceId, isNotFoundError } from "@/lib/workspace";
import { maybeCompressImage } from "@/lib/media";
import { useWorkspaceId } from "@/lib/useWorkspaceId";
import type { Document } from "@/lib/types";
import { formatDate, formatBytes, getMediaUrl } from "@/lib/utils";
import { FileText, Trash2, Upload, X, CheckSquare, Square, Info, Image as ImageIcon } from "lucide-react";

const STATUS_STYLE: Record<string, string> = {
  ready: "bg-emerald-500/15 text-emerald-700",
  processing: "bg-amber-500/15 text-amber-700",
  failed: "bg-red-500/15 text-red-700",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[status] ?? "bg-black/[.06] text-[#655f59]"}`}>
      {status === "processing" ? (
        <span className="mr-1 h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
      ) : null}
      {status}
    </span>
  );
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const { wsId, setWsId } = useWorkspaceId();
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadDocs = useCallback(async () => {
    setLoading(true);
    try {
      const workspaces = await apiFetch<import("@/lib/types").Workspace[]>("/api/workspaces");
      const allDocs: Document[] = [];
      for (const ws of workspaces) {
        try {
          const data = await apiFetch<Document[]>(`/api/documents?workspace_id=${ws.id}`);
          allDocs.push(...data);
        } catch { /* skip */ }
      }
      setDocs(allDocs);
    } catch (cause) {
      setError(friendlyError(cause).message);
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  async function uploadFile(id: string, file: File) {
    const compressed = await maybeCompressImage(file);
    const form = new FormData();
    form.append("file", compressed);
    await apiFetch<Document>(`/api/documents/upload?workspace_id=${id}`, { method: "POST", body: form });
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
      const data = await apiFetch<Document[]>(`/api/documents?workspace_id=${id}`);
      setDocs(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
    }
    setUploading(false);
  }

  async function handleDelete(id: string) {
    if (!wsId) return;
    try {
      await apiFetch(`/api/documents/${id}?workspace_id=${wsId}`, { method: "DELETE" });
      setDocs((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const n = new Set(prev); n.delete(id); return n; });
    } catch { setError("Delete failed."); }
  }

  async function deleteSelected() {
    if (!selected.size) return;
    setDeleting(true);
    await Promise.all([...selected].map((id) => handleDelete(id)));
    setSelected(new Set());
    setDeleting(false);
  }

  async function deleteAll() {
    if (!docs.length || !confirm(`Delete all ${docs.length} documents? This cannot be undone.`)) return;
    setDeleting(true);
    await Promise.all(docs.map((d) => handleDelete(d.id)));
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
    setSelected(selected.size === docs.length ? new Set() : new Set(docs.map((d) => d.id)));
  }

  return (
    <PageShell wide>
      {/* Header */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-editorial text-2xl font-medium italic tracking-tight">Documents</h1>
            <button
              onClick={() => setShowInfo(!showInfo)}
              className="rounded-full p-1 text-[#8d8780] hover:bg-black/[.06] hover:text-black"
              title="How are documents used?"
            >
              <Info size={15} />
            </button>
          </div>
          <p className="mt-1 text-sm text-[#655f59]">Upload PDFs, DOCX, TXT, Markdown, or images for AI-powered search</p>
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
          {docs.length > 0 && selected.size === 0 && (
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
            {uploading ? "Uploading…" : "Upload"}
            <input ref={inputRef} type="file" className="hidden" multiple accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.webp" onChange={handleUpload} />
          </label>
        </div>
      </div>

      {/* Info callout */}
      {showInfo && (
        <div className="mb-5 rounded-2xl border border-black/[.06] bg-white/60 p-4 text-sm text-[#24231f] backdrop-blur">
          <p className="font-semibold mb-1">How documents work in Emmaus</p>
          <ul className="list-disc pl-4 space-y-1 text-xs leading-relaxed text-[#655f59]">
            <li><strong>RAG (Retrieval-Augmented Generation)</strong> - Documents are chunked and embedded into a vector store. When you ask a question in chat, the AI searches relevant chunks and uses them as context.</li>
            <li><strong>Attach in chat</strong> - You can also attach files directly in the home chat box. They go into the active workspace automatically.</li>
            <li><strong>Images</strong> - Images are processed via Vision OCR; upload receipts, handwritten notes, charts, etc.</li>
            <li><strong>Status &quot;ready&quot;</strong> means the doc is indexed and searchable in your workspace chat.</li>
          </ul>
          <button onClick={() => setShowInfo(false)} className="mt-3 text-xs text-[#6366f1] underline">Dismiss</button>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-red-200/60 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur">
          <X size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => { setError(""); void loadDocs(); }} className="ml-auto shrink-0 rounded-full bg-[#282521] px-3 py-1 text-[11px] font-medium text-white transition hover:bg-black">Retry</button>
          <button onClick={() => setError("")} className="shrink-0 text-red-400 hover:text-red-600"><X size={12} /></button>
        </div>
      )}



      {loading ? (
        <div className="space-y-2">
          {[1,2,3].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-xl bg-white/50" />
          ))}
        </div>
      ) : docs.length === 0 ? (
        <div className="rounded-2xl border border-black/[.06] bg-white/50 py-16 text-center backdrop-blur">
          <FileText size={32} className="mx-auto mb-3 text-[#8d8780]/50" />
          <p className="text-sm font-medium text-[#655f59]">No documents yet</p>
          <p className="mt-1 text-xs text-[#8d8780]">Upload PDFs, DOCX, TXT, Markdown, or images above</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-black/[.06] bg-white/60 shadow-sm backdrop-blur">
          {/* Bulk action bar */}
          <div className="flex items-center gap-3 border-b border-black/[.06] bg-white/40 px-4 py-2.5">
            <button onClick={toggleAll} className="flex items-center gap-1.5 text-xs text-[#655f59] hover:text-black">
              {selected.size === docs.length && docs.length > 0 ? (
                <CheckSquare size={14} className="text-[#6366f1]" />
              ) : (
                <Square size={14} />
              )}
              {selected.size === docs.length && docs.length > 0 ? "Deselect all" : "Select all"}
            </button>
            <span className="text-xs text-[#8d8780]">{docs.length} document{docs.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-black/[.06]">
                  <th className="w-8 px-4 py-3" />
                  <th className="px-4 py-3 text-left text-xs font-medium text-[#6a635d]">Name</th>
                  <th className="hidden px-4 py-3 text-left text-xs font-medium text-[#6a635d] sm:table-cell">Type</th>
                  <th className="hidden px-4 py-3 text-left text-xs font-medium text-[#6a635d] sm:table-cell">Size</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-[#6a635d]">Status</th>
                  <th className="hidden px-4 py-3 text-left text-xs font-medium text-[#6a635d] md:table-cell">Uploaded</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr
                    key={doc.id}
                    className={`border-b border-black/[.04] transition last:border-0 ${selected.has(doc.id) ? "bg-[#6366f1]/[.07]" : "hover:bg-white/60"}`}
                  >
                    <td className="px-4 py-3">
                      <button onClick={() => toggleSelect(doc.id)}>
                        {selected.has(doc.id) ? <CheckSquare size={15} className="text-[#6366f1]" /> : <Square size={15} className="text-[#8d8780]/50" />}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {doc.source_type === "image" && doc.media_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={getMediaUrl(doc.media_url)}
                            alt={doc.filename}
                            className="h-8 w-8 rounded-lg object-cover ring-1 ring-black/10 shrink-0 cursor-pointer hover:ring-black/25 transition"
                            onClick={() => setPreviewId(doc.id)}
                            loading="lazy"
                          />
                        ) : doc.source_type === "image" ? (
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-indigo-50 text-indigo-500">
                            <ImageIcon size={13} />
                          </span>
                        ) : (
                          <FileText size={14} className="shrink-0 text-[#8d8780]" />
                        )}
                        <button
                          onClick={() => doc.source_type === "image" && doc.media_url && setPreviewId(doc.id)}
                          className={`truncate text-left font-medium max-w-[160px] sm:max-w-xs ${doc.source_type === "image" && doc.media_url ? "text-[#24231f] hover:underline cursor-pointer" : "text-[#24231f]"}`}
                        >
                          {doc.filename}
                        </button>
                      </div>
                    </td>
                    <td className="hidden px-4 py-3 text-xs text-[#655f59] sm:table-cell">{doc.source_type}</td>
                    <td className="hidden px-4 py-3 text-xs text-[#655f59] sm:table-cell">{formatBytes(doc.size_bytes)}</td>
                    <td className="px-4 py-3"><StatusBadge status={doc.status} /></td>
                    <td className="hidden px-4 py-3 text-xs text-[#8d8780] md:table-cell">{formatDate(doc.created_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="rounded-lg p-1.5 text-[#8d8780] transition hover:bg-red-50 hover:text-red-600"
                        title="Delete document"
                      >
                        <X size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Image lightbox — only for image docs with a stored URL */}
      {previewId && (() => {
        const doc = docs.find((d) => d.id === previewId);
        if (!doc?.media_url) return null;
        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
            onClick={() => setPreviewId(null)}
          >
            <div
              className="relative max-h-[85vh] max-w-[90vw] overflow-hidden rounded-2xl border border-white/20 bg-white shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={getMediaUrl(doc.media_url)} alt={doc.filename} className="max-h-[80vh] w-auto object-contain" />
              <div className="flex items-center justify-between border-t border-black/[.06] bg-[#fffdf8] px-4 py-2">
                <span className="truncate text-xs font-medium text-[#24231f]">{doc.filename}</span>
                <button
                  onClick={() => setPreviewId(null)}
                  className="ml-3 rounded-full p-1.5 text-[#8d8780] transition hover:bg-black/[.06] hover:text-black"
                  aria-label="Close preview"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </PageShell>
  );
}
