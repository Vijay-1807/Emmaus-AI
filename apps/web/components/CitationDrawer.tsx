"use client";

import { X, FileText, ExternalLink, BookmarkCheck } from "lucide-react";
import type { Citation } from "@/lib/types";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export default function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  if (!citation) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm transition-opacity animate-in fade-in">
      <div className="relative flex h-full w-full max-w-md flex-col bg-[#fffdfa] p-6 shadow-2xl transition-transform animate-in slide-in-from-right duration-200">
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-black/[.08] pb-4">
          <div className="flex items-center gap-2">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-[#6366f1]/10 text-[#4f46e5]">
              <FileText size={16} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#1c1917] truncate max-w-[240px]">
                {citation.document_name}
              </h3>
              <p className="text-[11px] text-[#78716c]">
                {citation.source_type.toUpperCase()} {citation.page ? `• Page ${citation.page}` : ""}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-[#78716c] hover:bg-black/[.05] hover:text-black transition"
          >
            <X size={16} />
          </button>
        </div>

        {/* Metadata Badges */}
        <div className="mt-4 flex flex-wrap gap-2">
          {citation.score != null && (
            <div className="flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 border border-emerald-200/50">
              <BookmarkCheck size={13} />
              <span>Match Score: {typeof citation.score === "number" ? Math.round(citation.score * 100) : citation.score}%</span>
            </div>
          )}
          {citation.section && (
            <div className="rounded-full bg-black/[.04] px-2.5 py-1 text-xs text-[#57534e]">
              Section: {citation.section}
            </div>
          )}
        </div>

        {/* Snippet Content */}
        <div className="mt-5 flex-1 overflow-y-auto">
          <label className="text-xs font-semibold uppercase tracking-wider text-[#a8a29e]">
            Retrieved Context Passage
          </label>
          <div className="mt-2 rounded-xl border border-black/[.06] bg-[#fbf9f4] p-4 text-sm leading-relaxed text-[#292524] shadow-inner font-serif">
            &ldquo;{citation.snippet}&rdquo;
          </div>

          {citation.media_url && (
            <div className="mt-4">
              <a
                href={citation.media_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-[#4338ca] hover:underline"
              >
                <ExternalLink size={13} />
                <span>View Original File Asset</span>
              </a>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-4 border-t border-black/[.08] pt-3 text-right">
          <button
            onClick={onClose}
            className="rounded-xl bg-[#282521] px-4 py-2 text-xs font-semibold text-white shadow transition hover:bg-black"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
}
