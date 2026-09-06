"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUp,
  Camera,
  FileText,
  Mic,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { GradientBackground } from "@/components/ui/pipo";
import Navbar from "@/components/Navbar";
import CameraCapture from "@/components/CameraCapture";
import VoiceRecordModal from "@/components/VoiceRecordModal";
import ImageGenerator from "@/components/ImageGenerator";
import AttachmentChips, { chipKey } from "@/components/AttachmentChips";
import SiteFooter from "@/components/SiteFooter";
import type { UploadProgressValue } from "@/components/ui/upload-progress";
import { apiFetch, ensureAnonymousSession } from "@/lib/api";
import { maybeCompressImage } from "@/lib/media";
import type { Document, Dataset, MediaAsset, Workspace } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState<number>(-1);
  const [librarySources, setLibrarySources] = useState<import("@/lib/workspace").LibrarySource[]>([]);
  const mentionDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryRef = useRef<HTMLTextAreaElement>(null);
  const [uploadProgress, setUploadProgress] = useState<Record<string, UploadProgressValue>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<Record<string, { id: string; kind: string }>>({});
  const [showAllWs, setShowAllWs] = useState(false);
  const [showCamera, setShowCamera] = useState(false);
  const [showVoice, setShowVoice] = useState(false);
  const [showImageGen, setShowImageGen] = useState(false);
  const filesRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ensureAnonymousSession().then(() => {
      loadWorkspaces();
    }).catch((e) => console.error("auth failed:", e));

    const onChanged = () => loadWorkspaces();
    window.addEventListener("vedax:workspaces-changed", onChanged);
    return () => window.removeEventListener("vedax:workspaces-changed", onChanged);
  }, []);

  async function loadWorkspaces() {
    try {
      const ws = await apiFetch<Workspace[]>("/api/workspaces");
      setWorkspaces(ws);
      if (ws.length > 0) {
        const stored = localStorage.getItem("vedax_workspace_id");
        const valid = ws.some((w) => w.id === stored);
        if (!valid) {
          localStorage.setItem("vedax_workspace_id", ws[0].id);
        }
      } else {
        localStorage.removeItem("vedax_workspace_id");
      }
    } catch (e) {
      console.error("loadWorkspaces failed:", e);
    }
  }

  function addFiles(selected: File[]) {
    if (selected.length === 0) return;
    setFiles((current) => [...current, ...selected].slice(0, 8));
    setUploadProgress((current) => {
      const next = { ...current };
      selected.forEach((file) => {
        next[chipKey(file)] = { stage: "queued", progress: 0 };
      });
      return next;
    });
  }

  // Draft workspace reused on send, so uploads finish BEFORE send is allowed.
  const draftPromise = useRef<Promise<string | null> | null>(null);

  async function ensureDraft(): Promise<string | null> {
    if (draftId) return draftId;
    if (!draftPromise.current) {
      draftPromise.current = (async () => {
        try {
          await ensureAnonymousSession();
          const ws = await apiFetch<Workspace>("/api/workspaces", {
            method: "POST",
            body: JSON.stringify({ name: "New investigation" }),
          });
          localStorage.setItem("vedax_workspace_id", ws.id);
          setDraftId(ws.id);
          window.dispatchEvent(new CustomEvent("vedax:workspaces-changed"));
          return ws.id;
        } catch {
          return null;
        }
      })().finally(() => {
        draftPromise.current = null;
      });
    }
    return draftPromise.current;
  }

  async function uploadEager(file: File) {
    const id = await ensureDraft();
    if (!id) {
      updateProgress(file, { stage: "failed", progress: 100, error: "No workspace" });
      return;
    }
    try {
      const meta = await uploadFile(id, file);
      if (meta) setUploaded((prev) => ({ ...prev, [chipKey(file)]: meta }));
    } catch (cause) {
      updateProgress(file, {
        stage: "failed",
        progress: 100,
        error: cause instanceof Error ? cause.message : "Upload failed",
      });
    }
  }

  // Compress at selection time so progress keys stay consistent, then upload now.
  async function addCompressed(selected: File[]) {
    const done = await Promise.all(selected.map((f) => maybeCompressImage(f)));
    addFiles(done);
    done.forEach((f) => void uploadEager(f));
  }

  const pendingUpload = files.some((f) => {
    const stage = uploadProgress[chipKey(f)]?.stage;
    return stage === "queued" || stage === "uploading" || stage === "processing";
  });

  function removeFile(file: File) {
    const key = chipKey(file);
    setFiles((current) => current.filter((f) => chipKey(f) !== key));
    setUploadProgress((current) => {
      const n = { ...current };
      delete n[key];
      return n;
    });
    setUploaded((current) => {
      const n = { ...current };
      delete n[key];
      return n;
    });
  }

  function selectFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files || []);
    event.target.value = "";
    void addCompressed(selected);
  }

  function handleQueryChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setQuery(val);
    const cursor = e.target.selectionStart ?? val.length;
    const textBeforeCursor = val.slice(0, cursor);
    const atIndex = textBeforeCursor.lastIndexOf("@");
    if (atIndex !== -1 && !textBeforeCursor.slice(atIndex).includes(" ")) {
      const q = textBeforeCursor.slice(atIndex + 1);
      setMentionQuery(q);
      setMentionIndex(atIndex);
      if (mentionDebounce.current) clearTimeout(mentionDebounce.current);
      mentionDebounce.current = setTimeout(async () => {
        try {
          const { listLibrarySources } = await import("@/lib/workspace");
          setLibrarySources(await listLibrarySources());
        } catch { /* ignore */ }
      }, 120);
    } else {
      setMentionQuery(null);
    }
  }

  function selectMention(sourceName: string) {
    if (mentionIndex === -1) return;
    const before = query.slice(0, mentionIndex);
    const after = query.slice(mentionIndex + (mentionQuery?.length ?? 0) + 1);
    const updated = `${before}@${sourceName} ${after}`;
    setQuery(updated);
    setMentionQuery(null);
    queryRef.current?.focus();
  }

  const mentionMatches =
    mentionQuery !== null
      ? librarySources
          .filter((s) => s.filename.toLowerCase().includes(mentionQuery.toLowerCase()))
          .slice(0, 8)
      : [];

  function updateProgress(file: File, value: UploadProgressValue) {
    setUploadProgress((current) => ({ ...current, [chipKey(file)]: value }));
  }

  async function waitForSource(
    path: "documents" | "datasets",
    wsId: string,
    id: string,
    file: File,
  ): Promise<void> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const source = await apiFetch<Document | Dataset>(`/api/${path}/${id}?workspace_id=${wsId}`);
      if (source.status === "ready") {
        updateProgress(file, { stage: "ready", progress: 100 });
        return;
      }
      if (source.status === "failed") throw new Error(source.error || "Source processing failed");
      updateProgress(file, { stage: "processing", progress: Math.min(95, 55 + attempt * 2) });
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error("Source processing timed out. Please try again.");
  }

  async function uploadFile(wsId: string, file: File): Promise<{ id: string; kind: string } | null> {
    updateProgress(file, { stage: "uploading", progress: 25 });
    const ext = file.name.split(".").pop()?.toLowerCase() || "";
    const form = new FormData();
    form.append("file", file);
    if (["csv", "xlsx", "xls"].includes(ext)) {
      const dataset = await apiFetch<Dataset>(`/api/datasets/upload?workspace_id=${wsId}`, { method: "POST", body: form });
      updateProgress(file, { stage: "processing", progress: 55 });
      await waitForSource("datasets", wsId, dataset.id, file);
      return null;
    }
    if (file.type.startsWith("image/") || file.type.startsWith("audio/")) {
      const media = await apiFetch<MediaAsset>(`/api/media/upload?workspace_id=${wsId}`, {
        method: "POST",
        body: form,
      });
      updateProgress(file, { stage: "ready", progress: 100 });
      return { id: media.id, kind: media.kind };
    }
    const document = await apiFetch<Document>(`/api/documents/upload?workspace_id=${wsId}`, { method: "POST", body: form });
    updateProgress(file, { stage: "processing", progress: 55 });
    await waitForSource("documents", wsId, document.id, file);
    return { id: document.id, kind: "document" };
  }

  async function launch() {
    // Send is only possible when every attachment is already at 100%.
    if (busy || pendingUpload || (!query.trim() && files.length === 0)) return;
    setMentionQuery(null);
    setBusy(true);
    setError("");
    try {
      await ensureAnonymousSession();
      let id = draftId;
      if (id) {
        await apiFetch(`/api/workspaces/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: query.trim().slice(0, 54) || "New investigation" }),
        }).catch(() => {});
      } else {
        const ws = await apiFetch<Workspace>("/api/workspaces", {
          method: "POST",
          body: JSON.stringify({ name: query.trim().slice(0, 54) || "New investigation" }),
        });
        id = ws.id;
      }
      localStorage.setItem("vedax_workspace_id", id);

      // Resolve @mentions: copy docs or datasets into the new workspace so RAG/data can see them.
      const mentionedIds: string[] = [];
      const atTokens = query.match(/@([^\s]+(?:\s+[^\s]+)*)/g) || [];
      for (const token of atTokens) {
        const raw = token.slice(1).trim();
        if (!raw) continue;
        const match = librarySources.find((s) => s.filename.toLowerCase() === raw.toLowerCase())
          ?? librarySources.find((s) => raw.toLowerCase().includes(s.filename.toLowerCase()))
          ?? librarySources.find((s) => s.filename.toLowerCase().includes(raw.toLowerCase()));
        if (!match || match.workspace_id === id) continue;
        try {
          const ws = await import("@/lib/workspace");
          const newId = match.source_type === "dataset"
            ? await ws.copyDatasetToWorkspace(match.workspace_id, match.id, id)
            : await ws.copyDocumentToWorkspace(match.workspace_id, match.id, id);
          if (newId) mentionedIds.push(newId);
        } catch { /* best-effort */ }
      }

      const metas = files
        .map((f) => uploaded[chipKey(f)])
        .filter((m): m is { id: string; kind: string } => Boolean(m));
      const attachmentIds = [
        ...mentionedIds,
        ...metas.filter((m) => m.kind === "image" || m.kind === "document").map((m) => m.id),
      ];
      const audioMediaId = metas.find((m) => m.kind === "audio")?.id;
      localStorage.setItem(
        `vedax_pending_${id}`,
        JSON.stringify({ message: query.trim() || "Analyze the attached source.", attachmentIds, audioMediaId })
      );
      router.push(`/workspace/${id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to start the investigation.");
      setBusy(false);
    }
  }

  async function deleteWorkspace(id: string) {
    try {
      await apiFetch(`/api/workspaces/${id}`, { method: "DELETE" });
    } catch (e) {
      // Already gone on the server (stale id) — still prune it locally.
      if (!(e instanceof Error) || !/not found/i.test(e.message)) {
        console.error("deleteWorkspace failed:", e);
        return;
      }
    }
    setWorkspaces((prev) => prev.filter((w) => w.id !== id));
    if (localStorage.getItem("vedax_workspace_id") === id) {
      localStorage.removeItem("vedax_workspace_id");
    }
  }

  function openWorkspace(id: string) {
    localStorage.setItem("vedax_workspace_id", id);
    router.push(`/workspace/${id}`);
  }

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-[#faf9ef] text-[#24231f]">
      <GradientBackground className="fixed inset-0" />
      <Navbar />

      <section className="relative z-10 mx-auto flex min-h-[calc(100svh-80px)] max-w-4xl flex-col items-center justify-center px-4 pb-20 sm:px-8">
        <div className="mb-5 text-center sm:mb-6">
          <h1 className="text-balance font-editorial text-3xl font-medium tracking-[-0.02em] sm:text-4xl lg:text-5xl">
            What should we <em className="italic">investigate?</em>
          </h1>
          <p className="mx-auto mt-2 max-w-lg text-[11px] leading-4 text-[#655f59] sm:mt-3 sm:text-sm sm:leading-5">
            Ask a question or add documents, datasets, images, and audio.
          </p>
        </div>

        {/* Composer Card */}
        <div className="w-full max-w-2xl rounded-[24px] border border-white/50 bg-white/40 p-1.5 shadow-[0_16px_60px_rgba(77,63,54,.12)] backdrop-blur-xl">
          <div className="rounded-[20px] border border-black/[.06] bg-[#fffdf8]/80 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,.9)]">
            {/* @-mention picker: surfaces documents + datasets from your whole library */}
            {mentionQuery !== null && (() => {
              const docs = mentionMatches.filter((s) => s.source_type !== "dataset");
              const datasets = mentionMatches.filter((s) => s.source_type === "dataset");
              return (
                <div className="mb-1 max-h-52 overflow-y-auto rounded-xl border border-black/[.06] bg-white py-1 shadow-sm">
                  {mentionMatches.length === 0 ? (
                    <div className="px-3 py-2 text-xs text-[#8d8780]">
                      {librarySources.length === 0 ? "Nothing here yet - upload a doc or dataset first, then type @" : "No match - try a shorter word."}
                    </div>
                  ) : (
                    <>
                      {docs.length > 0 && <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[#8d8780]">Documents</div>}
                      {docs.map((s) => (
                        <button key={s.id} onClick={() => selectMention(s.filename)} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs transition hover:bg-black/[.05]">
                          <span className="truncate font-medium">{s.filename}</span>
                          <span className="ml-2 shrink-0 text-[10px] text-[#8d8780]">{s.source_type}</span>
                        </button>
                      ))}
                      {datasets.length > 0 && <div className={`${docs.length ? "mt-1 border-t border-black/[.04] pt-1 " : ""}px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[#6366f1]`}>Datasets</div>}
                      {datasets.map((s) => (
                        <button key={s.id} onClick={() => selectMention(s.filename)} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs transition hover:bg-black/[.05]">
                          <span className="truncate font-medium">{s.filename}</span>
                          <span className="ml-2 shrink-0 rounded-full bg-[#6366f1]/10 px-1.5 py-0.5 text-[10px] font-medium text-[#6366f1]">dataset</span>
                        </button>
                      ))}
                    </>
                  )}
                </div>
              );
            })()}
            <textarea
              ref={queryRef}
              autoFocus
              value={query}
              onChange={handleQueryChange}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setMentionQuery(null);
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  setMentionQuery(null);
                  void launch();
                }
              }}
              placeholder="Ask anything about your sources... (type @ to reuse any document)"
              rows={2}
              className="min-h-14 w-full resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-[#8d8780]"
            />

            <AttachmentChips
              files={files}
              progress={uploadProgress}
              onRemove={removeFile}
              canRemove={!busy}
            />
            {pendingUpload && (
              <p className="px-1 pb-1 text-[11px] text-[#8d8780]">
                Uploading attachments… send unlocks at 100%.
              </p>
            )}

            {showImageGen && (
              <div className="border-t border-black/[.06] pt-2 mt-1">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-medium text-[#8d8780] uppercase tracking-wider">Image Generation</span>
                  <button onClick={() => setShowImageGen(false)} className="rounded p-0.5 text-[#8d8780] hover:bg-black/[.05]">
                    <X size={10} />
                  </button>
                </div>
                <ImageGenerator workspaceId={draftId || workspaces[0]?.id || ""} />
              </div>
            )}

            <div className="flex items-center justify-between border-t border-black/[.06] pt-1.5">
              <div className="flex items-center gap-0.5">
                <ToolBtn icon={<FileText size={14} />} label="Upload" onClick={() => filesRef.current?.click()} />
                <ToolBtn icon={<Camera size={14} />} label="Camera" onClick={() => setShowCamera(true)} />
                <ToolBtn icon={<Mic size={14} />} label="Voice" onClick={() => setShowVoice(true)} />
                <ToolBtn icon={<Sparkles size={14} />} label="Image Gen" onClick={() => void (async () => {
                  if (showImageGen) {
                    setShowImageGen(false);
                    return;
                  }
                  // Mobile with zero workspaces: create the draft first,
                  // otherwise the panel has no workspace to generate into.
                  if (!draftId && workspaces.length === 0) await ensureDraft();
                  setShowImageGen(true);
                })()} />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="hidden text-[10px] text-[#8d8780] sm:block">Groq &middot; 120B</span>
                <button
                  onClick={() => void launch()}
                  disabled={busy || pendingUpload || (!query.trim() && files.length === 0)}
                  aria-label="Send"
                  className="grid h-8 w-8 place-items-center rounded-full bg-[#282521] text-white shadow-md transition hover:-translate-y-0.5 hover:bg-black disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {busy ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/35 border-t-white" /> : <ArrowUp size={16} />}
                </button>
              </div>
            </div>
          </div>
        </div>

        {error && <p role="alert" className="mt-3 rounded-full bg-red-950/85 px-4 py-1.5 text-xs text-white shadow-lg">{error}</p>}

        {/* Workspace cards — latest 2, expandable */}
        {workspaces.length > 0 && (
          <div className="mt-12 w-full max-w-3xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.15em] text-[#6a635d]">Your Workspaces</h2>
              {workspaces.length > 2 && (
                <button
                  onClick={() => setShowAllWs((v) => !v)}
                  className="rounded-full border border-black/[.08] bg-white/50 px-3 py-1 text-[11px] font-medium text-[#655f59] backdrop-blur transition hover:bg-white/80 hover:text-black"
                >
                  {showAllWs ? "Show less" : `View all workspaces (${workspaces.length})`}
                </button>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(showAllWs ? workspaces : workspaces.slice(0, 2)).map((ws) => (
                <div
                  key={ws.id}
                  className="group flex items-start justify-between rounded-2xl border border-black/[.06] bg-white/50 p-4 text-left backdrop-blur transition hover:border-black/[.12] hover:bg-white/70 cursor-pointer"
                  onClick={() => openWorkspace(ws.id)}
                >
                  <div>
                    <div className="text-sm font-semibold">{ws.name}</div>
                    {ws.description && <div className="mt-0.5 text-xs text-[#655f59]">{ws.description}</div>}
                    <div className="mt-1 text-[11px] text-[#8d8780]">{formatDate(ws.created_at)}</div>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteWorkspace(ws.id); }}
                    className="mt-0.5 rounded-lg p-1 text-[#8d8780] opacity-100 transition hover:text-red-600 md:opacity-0 md:group-hover:opacity-100"
                    title="Delete workspace"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Device showcase — laptop + phone mockups, Telegram bot link */}
      <section className="relative z-10 mx-auto w-full max-w-5xl px-4 pb-4 text-center sm:px-8">
        <h2 className="font-editorial text-2xl font-medium tracking-[-0.02em] sm:text-3xl">
          Take Emmaus <em className="italic">anywhere</em>
        </h2>
        <p className="mx-auto mt-2 max-w-md text-[11px] leading-4 text-[#655f59] sm:text-sm sm:leading-5">
          Full workspace on your laptop, quick answers in your pocket.
        </p>
        <div className="mx-auto mt-5 max-w-3xl overflow-hidden rounded-2xl border border-black/[.06] bg-white/50 shadow-[0_16px_60px_rgba(77,63,54,.12)] backdrop-blur-xl">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/device-shot.svg" alt="Emmaus AI on laptop and mobile" className="h-auto w-full" loading="lazy" />
        </div>
        <a
          href="https://t.me/EmmausAIBot"
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#282521] px-5 py-2.5 text-sm font-medium text-white shadow-md transition hover:-translate-y-0.5 hover:bg-black"
        >
          <Send size={14} />
          Chat with @EmmausAIBot on Telegram
        </a>
      </section>

      {/* Footer on our own Pipo background */}
      <div className="relative z-10 mx-auto w-full max-w-7xl px-4 pb-12 sm:px-8">
        <SiteFooter />
      </div>

      <input ref={filesRef} type="file" multiple className="hidden" onChange={selectFiles} accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls,image/*,audio/*" />

      {showCamera && (
        <CameraCapture
          onCapture={(blob, filename) => {
            setShowCamera(false);
            void addCompressed([new File([blob], filename, { type: blob.type || "image/jpeg" })]);
          }}
          onClose={() => setShowCamera(false)}
        />
      )}

      {showVoice && (
        <VoiceRecordModal
          isOpen={showVoice}
          onClose={() => setShowVoice(false)}
          onAudioReady={(file) => { void addCompressed([file]); }}
        />
      )}
    </main>
  );
}

function ToolBtn({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-label={label} title={label} className="flex items-center gap-1 rounded-full px-2.5 py-1.5 text-[11px] text-[#5f5953] transition hover:bg-black/[.06] hover:text-black">
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
