"use client";

import { Check, FileText, Loader2, TriangleAlert } from "lucide-react";
import { formatBytes } from "@/lib/utils";

export type UploadStage = "queued" | "uploading" | "processing" | "ready" | "failed";

export interface UploadProgressValue {
  stage: UploadStage;
  progress: number;
  error?: string;
}

const labels: Record<UploadStage, string> = {
  queued: "Ready to upload",
  uploading: "Uploading",
  processing: "Indexing for search",
  ready: "Ready",
  failed: "Upload failed",
};

export function UploadProgress({ file, value }: { file: File; value: UploadProgressValue }) {
  const active = value.stage === "uploading" || value.stage === "processing";
  return (
    <div className="rounded-xl border border-black/[.07] bg-white/60 px-3 py-2.5 shadow-sm">
      <div className="flex items-center gap-2.5">
        <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-black/[.05] text-[#655f59]">
          {active ? <Loader2 size={15} className="animate-spin" /> : value.stage === "ready" ? <Check size={15} /> : value.stage === "failed" ? <TriangleAlert size={15} /> : <FileText size={15} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-xs font-medium">{file.name}</span>
            <span className="shrink-0 text-[10px] text-[#8d8780]">{formatBytes(file.size)}</span>
          </div>
          <div className="mt-0.5 flex items-center justify-between text-[10px]">
            <span className={value.stage === "failed" ? "text-red-600" : "text-[#655f59]"}>{value.error || labels[value.stage]}</span>
            <span className="font-mono text-[#8d8780] tabular-nums">{Math.round(value.progress)}%</span>
          </div>
        </div>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-black/[.07]">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${value.stage === "failed" ? "bg-red-500" : value.stage === "ready" ? "bg-emerald-500" : "bg-[#282521]"}`}
          style={{ width: `${value.progress}%` }}
        />
      </div>
    </div>
  );
}
