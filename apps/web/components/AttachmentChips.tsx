"use client";

import { useEffect, useMemo } from "react";
import { FileText, X } from "lucide-react";
import type { UploadProgressValue } from "@/components/ui/upload-progress";

export function chipKey(file: File): string {
  return `${file.name}-${file.size}-${file.lastModified}`;
}

interface AttachmentChipsProps {
  files: File[];
  progress: Record<string, UploadProgressValue>;
  onRemove: (file: File) => void;
  canRemove?: boolean;
}

/** Shared attachment chips (thumbnail + status + % + bar). Used by Home and workspace chat. */
export default function AttachmentChips({ files, progress, onRemove, canRemove = true }: AttachmentChipsProps) {
  const previews = useMemo(() => {
    const map = new Map<string, string>();
    files.forEach((f) => {
      if (f.type.startsWith("image/")) {
        try {
          map.set(chipKey(f), URL.createObjectURL(f));
        } catch {
          /* ignore */
        }
      }
    });
    return map;
  }, [files]);

  useEffect(() => () => {
    previews.forEach((url) => URL.revokeObjectURL(url));
  }, [previews]);

  if (files.length === 0) return null;

  return (
    <div className="mb-2.5 flex flex-wrap gap-2 px-0.5 pt-0.5">
      {files.map((file) => {
        const key = chipKey(file);
        const prog = progress[key] || { stage: "queued" as const, progress: 0 };
        const isUploading = prog.stage === "uploading" || prog.stage === "processing";
        const isReady = prog.stage === "ready";
        const isFailed = prog.stage === "failed";
        const previewUrl = previews.get(key) ?? null;
        return (
          <div
            key={key}
            className={`group relative flex items-center gap-2.5 rounded-2xl border px-3 py-2 text-xs transition shadow-sm ${
              isFailed
                ? "border-red-200 bg-red-50 text-red-700"
                : isUploading
                ? "border-indigo-200 bg-indigo-50/70 text-indigo-900"
                : isReady
                ? "border-emerald-200 bg-emerald-50/70 text-emerald-900"
                : "border-black/[.08] bg-white/90 text-[#44403c]"
            }`}
          >
            {previewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={previewUrl} alt={file.name} className="h-9 w-9 rounded-xl object-cover ring-1 ring-black/10 shrink-0" />
            ) : (
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-black/[.05] text-[#6a635d]">
                <FileText size={16} />
              </span>
            )}
            <div className="min-w-0 pr-1">
              <div className="flex items-center gap-1.5">
                <p className="max-w-[120px] truncate font-medium leading-tight text-[12px]">{file.name}</p>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className="text-[10px] font-medium opacity-75">
                  {isFailed
                    ? prog.error || "Failed"
                    : isUploading
                    ? `${prog.stage === "processing" ? "Indexing" : "Uploading"}…`
                    : isReady
                    ? "Ready"
                    : "Queued"}
                </span>
                <span className="text-[10px] font-mono font-bold">
                  {isFailed ? "!" : `${Math.round(prog.progress)}%`}
                </span>
              </div>
              {/* Progress bar */}
              <div className="mt-1 h-1 w-24 overflow-hidden rounded-full bg-black/[.08]">
                <div
                  className={`h-full transition-all duration-300 ${
                    isFailed
                      ? "bg-red-500"
                      : isReady
                      ? "bg-emerald-500"
                      : isUploading
                      ? "bg-indigo-600 animate-pulse"
                      : "bg-gray-300"
                  }`}
                  style={{ width: `${Math.max(5, prog.progress)}%` }}
                />
              </div>
            </div>
            {/* X remove button */}
            {canRemove && (
              <button
                onClick={() => onRemove(file)}
                aria-label={`Remove ${file.name}`}
                className="shrink-0 rounded-full p-1 text-[#8d8780] transition hover:bg-black/[.08] hover:text-black"
                title="Remove file"
              >
                <X size={13} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
