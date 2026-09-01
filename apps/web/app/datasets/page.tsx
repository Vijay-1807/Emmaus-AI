"use client";

import { useEffect, useState, useCallback } from "react";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { Dataset } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [wsId, setWsId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadDatasets = useCallback(async () => {
    if (!wsId) return;
    setLoading(true);
    try {
      const data = await apiFetch<Dataset[]>(`/api/datasets?workspace_id=${wsId}`);
      setDatasets(data);
    } catch {}
    setLoading(false);
  }, [wsId]);

  useEffect(() => {
    const stored = localStorage.getItem("vedax_workspace_id") || "";
    setWsId(stored);
  }, []);

  useEffect(() => { loadDatasets(); }, [loadDatasets]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !wsId) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("workspace_id", wsId);
      await apiFetch<Dataset>("/api/datasets/upload", { method: "POST", body: form, headers: {} });
      await loadDatasets();
    } catch {}
    setUploading(false);
    e.target.value = "";
  }

  return (
    <AppLayout>
      <div className="p-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Datasets</h1>
            <p className="text-text-muted text-sm mt-1">Upload CSV and XLSX files for data analysis</p>
          </div>
          <label className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-hover transition-colors cursor-pointer">
            {uploading ? "Uploading..." : "Upload dataset"}
            <input type="file" className="hidden" accept=".csv,.xlsx,.xls" onChange={handleUpload} />
          </label>
        </div>

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : datasets.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No datasets yet</p>
            <p className="text-sm">Upload CSV or XLSX files for analysis.</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {datasets.map((ds) => (
              <div key={ds.id} className="bg-surface border border-border rounded-xl p-5">
                <h3 className="font-medium mb-1 truncate">{ds.filename}</h3>
                <div className="text-text-muted text-sm space-y-1">
                  <p>{ds.num_rows} rows &middot; {ds.columns.length} columns</p>
                  <p className={`text-xs ${ds.status === "ready" ? "text-success" : ds.status === "failed" ? "text-error" : "text-warning"}`}>
                    {ds.status}
                  </p>
                  <p className="text-xs">{formatDate(ds.created_at)}</p>
                </div>
                {ds.columns.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {ds.columns.slice(0, 5).map((col) => (
                      <span key={col.name} className="px-2 py-0.5 bg-bg border border-border rounded text-xs text-text-muted">
                        {col.name}
                      </span>
                    ))}
                    {ds.columns.length > 5 && (
                      <span className="px-2 py-0.5 text-xs text-text-muted">+{ds.columns.length - 5}</span>
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
