"use client";

import { useEffect, useState, useCallback } from "react";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { Document } from "@/lib/types";
import { formatDate, formatBytes } from "@/lib/utils";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [wsId, setWsId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadDocs = useCallback(async () => {
    if (!wsId) return;
    setLoading(true);
    try {
      const data = await apiFetch<Document[]>(`/api/documents?workspace_id=${wsId}`);
      setDocs(data);
    } catch {}
    setLoading(false);
  }, [wsId]);

  useEffect(() => {
    const stored = localStorage.getItem("vedax_workspace_id") || "";
    setWsId(stored);
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !wsId) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("workspace_id", wsId);
      await apiFetch<Document>("/api/documents/upload", { method: "POST", body: form, headers: {} });
      await loadDocs();
    } catch {}
    setUploading(false);
    e.target.value = "";
  }

  async function handleDelete(id: string) {
    if (!wsId || !confirm("Delete this document?")) return;
    try {
      await apiFetch(`/api/documents/${id}?workspace_id=${wsId}`, { method: "DELETE" });
      setDocs((prev) => prev.filter((d) => d.id !== id));
    } catch {}
  }

  const STATUS_COLORS: Record<string, string> = {
    ready: "text-success",
    processing: "text-warning",
    failed: "text-error",
  };

  return (
    <AppLayout>
      <div className="p-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Documents</h1>
            <p className="text-text-muted text-sm mt-1">Upload and manage documents for RAG</p>
          </div>
          <label className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-hover transition-colors cursor-pointer">
            {uploading ? "Uploading..." : "Upload document"}
            <input type="file" className="hidden" accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.webp" onChange={handleUpload} />
          </label>
        </div>

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : docs.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No documents yet</p>
            <p className="text-sm">Upload PDFs, DOCX, TXT, Markdown, or images.</p>
          </div>
        ) : (
          <div className="border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Name</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Type</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Size</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Chunks</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-text-muted font-medium">Uploaded</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {docs.map((doc) => (
                  <tr key={doc.id} className="border-b border-border hover:bg-surface-2 transition-colors">
                    <td className="px-4 py-3 text-text">{doc.filename}</td>
                    <td className="px-4 py-3 text-text-muted">{doc.source_type}</td>
                    <td className="px-4 py-3 text-text-muted">{formatBytes(doc.size_bytes)}</td>
                    <td className="px-4 py-3 text-text-muted">{doc.num_chunks}</td>
                    <td className={`px-4 py-3 ${STATUS_COLORS[doc.status] || "text-text-muted"}`}>
                      {doc.status}
                    </td>
                    <td className="px-4 py-3 text-text-muted text-xs">{formatDate(doc.created_at)}</td>
                    <td className="px-4 py-3">
                      <button onClick={() => handleDelete(doc.id)} className="text-text-muted hover:text-error text-xs">Delete</button>
                    </td>
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
