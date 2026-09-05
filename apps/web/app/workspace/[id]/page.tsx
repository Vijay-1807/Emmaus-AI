"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowUp, Camera, Trash2, AlertTriangle, Paperclip, Mic, Sparkles } from "lucide-react";
import type { UploadProgressValue } from "@/components/ui/upload-progress";
import ReactMarkdown from "react-markdown";
import { GradientBackground } from "@/components/ui/pipo";
import LoadingState from "@/components/ui/loading-state";
import CameraCapture from "@/components/CameraCapture";
import VoiceRecordModal from "@/components/VoiceRecordModal";
import ImageGenerator from "@/components/ImageGenerator";
import AttachmentChips, { chipKey } from "@/components/AttachmentChips";
import ChartViewer from "@/components/ui/ChartViewer";
import AgentPipelineTracker, { type PipelineNodeEvent } from "@/components/AgentPipelineTracker";
import CitationDrawer from "@/components/CitationDrawer";
import { apiFetch, apiRequest, ensureAnonymousSession } from "@/lib/api";
import { clearStoredWorkspaceIdIf, isNotFoundError } from "@/lib/workspace";
import { maybeCompressImage } from "@/lib/media";
import type { Document, Dataset, Citation, Chart, Evidence, Conversation, MediaAsset, Message as SavedMessage, Workspace } from "@/lib/types";
import { formatBytes, getMediaUrl } from "@/lib/utils";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  charts?: Chart[];
  evidence?: Evidence[];
  confidence?: number | null;
}

export default function WorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const wsId = params.id as string;
  const [documents, setDocuments] = useState<Document[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [mediaList, setMediaList] = useState<MediaAsset[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [showCamera, setShowCamera] = useState(false);
  const [showVoiceModal, setShowVoiceModal] = useState(false);
  const [showImageGenerator, setShowImageGenerator] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [pipelineEvents, setPipelineEvents] = useState<PipelineNodeEvent[]>([]);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [clearModalOpen, setClearModalOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [gone, setGone] = useState(false);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState<number>(-1);
  // Pending file attachments in chat input
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploadedChips, setUploadedChips] = useState<Record<string, { id: string; kind: string }>>({});
  const [chipProgress, setChipProgress] = useState<Record<string, UploadProgressValue>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sendingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  async function uploadWorkspaceFile(file: File) {
    const key = chipKey(file);
    const ext = file.name.split(".").pop()?.toLowerCase() || "";
    const form = new FormData();
    form.append("file", file);
    setChipProgress((prev) => ({ ...prev, [key]: { stage: "uploading", progress: 20 } }));
    
    // Create abort controller for this upload
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    
    try {
      if (file.type.startsWith("image/") || file.type.startsWith("audio/")) {
        const m = await apiFetch<MediaAsset>(`/api/media/upload?workspace_id=${wsId}`, { method: "POST", body: form });
        if (abortController.signal.aborted) return;
        setUploadedChips((prev) => ({ ...prev, [key]: { id: m.id, kind: m.kind } }));
        setChipProgress((prev) => ({ ...prev, [key]: { stage: "ready", progress: 100 } }));
        // Add to local media list so sources panel updates
        setMediaList((prev) => [...prev, m]);
      } else if (["csv", "xlsx", "xls"].includes(ext)) {
        const ds = await apiFetch<Dataset>(`/api/datasets/upload?workspace_id=${wsId}`, { method: "POST", body: form });
        if (abortController.signal.aborted) return;
        setChipProgress((prev) => ({ ...prev, [key]: { stage: "processing", progress: 60 } }));
        // Poll until ready with abort support
        for (let i = 0; i < 60; i++) {
          if (abortController.signal.aborted) return;
          const s = await apiFetch<Dataset>(`/api/datasets/${ds.id}?workspace_id=${wsId}`);
          if (s.status === "ready") break;
          if (s.status === "failed") throw new Error(s.error || "Dataset processing failed");
          setChipProgress((prev) => ({ ...prev, [key]: { stage: "processing", progress: Math.min(95, 60 + i * 2) } }));
          await new Promise((r) => setTimeout(r, 500));
        }
        if (abortController.signal.aborted) return;
        setUploadedChips((prev) => ({ ...prev, [key]: { id: ds.id, kind: "dataset" } }));
        setChipProgress((prev) => ({ ...prev, [key]: { stage: "ready", progress: 100 } }));
        setDatasets((prev) => [...prev, ds]);
      } else {
        const doc = await apiFetch<Document>(`/api/documents/upload?workspace_id=${wsId}`, { method: "POST", body: form });
        if (abortController.signal.aborted) return;
        setChipProgress((prev) => ({ ...prev, [key]: { stage: "processing", progress: 60 } }));
        for (let i = 0; i < 120; i++) {
          if (abortController.signal.aborted) return;
          const s = await apiFetch<Document>(`/api/documents/${doc.id}?workspace_id=${wsId}`);
          if (s.status === "ready") break;
          if (s.status === "failed") throw new Error(s.error || "Document processing failed");
          setChipProgress((prev) => ({ ...prev, [key]: { stage: "processing", progress: Math.min(95, 60 + i * 3) } }));
          await new Promise((r) => setTimeout(r, 400));
        }
        if (abortController.signal.aborted) return;
        setUploadedChips((prev) => ({ ...prev, [key]: { id: doc.id, kind: "document" } }));
        setChipProgress((prev) => ({ ...prev, [key]: { stage: "ready", progress: 100 } }));
        setDocuments((prev) => [...prev, doc]);
      }
    } catch (err) {
      if (abortController.signal.aborted) return;
      setChipProgress((prev) => ({
        ...prev,
        [key]: { stage: "failed", progress: 100, error: err instanceof Error ? err.message : "Upload failed" },
      }));
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
    }
  }

  // Compress at selection time so chip progress keys stay consistent.
  async function addWorkspaceFiles(selected: File[]) {
    const done = await Promise.all(selected.map((f) => maybeCompressImage(f)));
    setPendingFiles((prev) => [...prev, ...done].slice(0, 8));
    // Upload immediately in background
    done.forEach((f) => void uploadWorkspaceFile(f));
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files || []);
    if (!selected.length) return;
    e.target.value = "";
    void addWorkspaceFiles(selected);
  }

  function removeChip(file: File) {
    const key = chipKey(file);
    setPendingFiles((prev) => prev.filter((f) => chipKey(f) !== key));
    setUploadedChips((prev) => { const n = { ...prev }; delete n[key]; return n; });
    setChipProgress((prev) => { const n = { ...prev }; delete n[key]; return n; });
  }

  async function handleClearWorkspace() {
    if (!wsId || clearing) return;
    setClearing(true);
    try {
      await apiFetch(`/api/workspaces/${wsId}/clear`, { method: "POST" });
      setDocuments([]);
      setDatasets([]);
      setMessages([]);
      setPipelineEvents([]);
      setClearModalOpen(false);
    } catch (err) {
      console.error("Failed to clear workspace:", err);
    } finally {
      setClearing(false);
    }
  }

  useEffect(() => {
    if (!wsId) return;
    localStorage.setItem("vedax_workspace_id", wsId);
    async function initializeWorkspace() {
      await ensureAnonymousSession().catch(() => {});
      // Existence check first: a stale localStorage id (deleted workspace)
      // otherwise causes 404 spam across every downstream fetch.
      try {
        await apiFetch<Workspace>(`/api/workspaces/${wsId}`);
      } catch (cause) {
        if (isNotFoundError(cause)) {
          clearStoredWorkspaceIdIf(wsId);
          localStorage.removeItem(`vedax_pending_${wsId}`);
          setGone(true);
          return;
        }
      }
      try {
        const [loadedDocuments, loadedDatasets, loadedMedia, conversations] = await Promise.all([
          apiFetch<Document[]>(`/api/documents?workspace_id=${wsId}`),
          apiFetch<Dataset[]>(`/api/datasets?workspace_id=${wsId}`),
          apiFetch<MediaAsset[]>(`/api/media?workspace_id=${wsId}`).catch(() => []),
          apiFetch<Conversation[]>(`/api/chat/conversations?workspace_id=${wsId}`),
        ]);
        setDocuments(loadedDocuments);
        setDatasets(loadedDatasets);
        setMediaList(loadedMedia);
        if (conversations[0]) {
          setConversationId(conversations[0].id);
          const history = await apiFetch<{ messages: SavedMessage[] }>(
            `/api/chat/conversations/${conversations[0].id}/messages?workspace_id=${wsId}`,
          );
          setMessages(history.messages.map((message) => ({
            role: message.role,
            content: message.content,
            citations: message.citations,
            charts: message.charts,
            confidence: message.confidence,
          })));
        }
      } catch (cause) {
        // Race: workspace deleted between the existence check and now.
        if (isNotFoundError(cause)) {
          clearStoredWorkspaceIdIf(wsId);
          setGone(true);
          return;
        }
        console.error("workspace init failed:", cause);
        setDocuments([]);
        setDatasets([]);
      }

      const pendingKey = `vedax_pending_${wsId}`;
      const pending = localStorage.getItem(pendingKey);
      if (pending) {
        localStorage.removeItem(pendingKey);
        try {
          const payload = JSON.parse(pending) as { message: string; attachmentIds?: string[]; audioMediaId?: string };
          await sendMessage(payload.message, payload.attachmentIds || [], payload.audioMediaId);
        } catch (cause) {
          console.error("pending investigation failed:", cause);
        }
      }
    }

    void initializeWorkspace();
  // Intentional: initialization is keyed only by workspace id.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  // Cleanup effect: cancel ongoing operations on unmount
  useEffect(() => {
    return () => {
      // Cancel any ongoing upload polling
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      // Cancel any ongoing streaming reader
      if (readerRef.current) {
        readerRef.current.cancel().catch(() => {});
        readerRef.current = null;
      }
    };
  }, []);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(scrollToBottom, [messages, scrollToBottom]);

  async function sendMessage(message?: string, attachmentIds: string[] = [], audioMediaId?: string) {
    const text = (message ?? input).trim();
    if (!text && pendingFiles.length === 0) return;
    if (sendingRef.current) return;
    sendingRef.current = true;
    // Collect attachment IDs from uploaded chips
    const chipAttachments = pendingFiles
      .map((f) => uploadedChips[chipKey(f)])
      .filter((c) => c && (c.kind === "image" || c.kind === "document"))
      .map((c) => c.id);
    const chipAudio = pendingFiles
      .map((f) => uploadedChips[chipKey(f)])
      .find((c) => c?.kind === "audio")?.id;
    const finalAttachments = [...attachmentIds, ...chipAttachments];
    const finalAudioId = audioMediaId || chipAudio;
    // Clear chips
    setPendingFiles([]);
    setUploadedChips({});
    setChipProgress({});
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    setStreaming(true);
    setPipelineEvents([]);
    setActiveNode("classify");

    // Create abort controller for this request
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    try {
      const res = await apiRequest("/api/chat/stream", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: wsId,
          message: text || `Analyze the attached file(s).`,
          conversation_id: conversationId,
          attachment_ids: finalAttachments,
          audio_media_id: finalAudioId,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || "Unable to start investigation.");
      }

      reader = res.body?.getReader() ?? null;
      if (!reader) throw new Error("The server returned an empty response.");
      readerRef.current = reader;
      
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantContent = "";
      let assistantCitations: Citation[] = [];
      let assistantCharts: Chart[] = [];
      let assistantEvidence: Evidence[] = [];
      let confidence: number | null = null;

      while (true) {
        // Check if component unmounted or request was cancelled
        if (abortController.signal.aborted) break;
        
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[STREAM_END]") continue;
          try {
            const event = JSON.parse(data);
            if (event.type === "node") {
              setActiveNode(event.node);
              setPipelineEvents((prev) => [
                ...prev,
                { node: event.node, detail: event.detail, timestamp: Date.now() },
              ]);
            } else if (event.type === "token") {
              assistantContent += event.text;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantContent,
                };
                return updated;
              });
            } else if (event.type === "evidence") {
              assistantEvidence = event.evidence || [];
            } else if (event.type === "done") {
              setActiveNode(null);
              const inv = event.investigation;
              if (inv) {
                setConversationId(inv.conversation_id || null);
                assistantCitations = inv.citations || [];
                assistantCharts = inv.charts || [];
                confidence = inv.confidence;
              }
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantContent || "No response generated.",
                  citations: assistantCitations,
                  charts: assistantCharts,
                  evidence: assistantEvidence,
                  confidence,
                };
                return updated;
              });
            } else if (event.type === "error") {
              setActiveNode(null);
              assistantContent = event.message || "An error occurred.";
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = { role: "assistant", content: assistantContent };
                return updated;
              });
            }
          } catch {}
        }
      }
    } catch (err) {
      if (abortController.signal.aborted) return;
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Connection failed"}` };
        return updated;
      });
    } finally {
      // Clean up reader
      if (reader) {
        try {
          await reader.cancel();
        } catch {}
        readerRef.current = null;
      }
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      sendingRef.current = false;
      setStreaming(false);
    }
  }

  const allSources = [
    ...documents.map((d) => ({ name: d.filename, type: "document" as const })),
    ...datasets.map((ds) => ({ name: ds.filename, type: "dataset" as const })),
    ...mediaList.map((m) => ({ name: m.filename, type: "media" as const })),
  ];

  const matchingSources = mentionQuery !== null
    ? allSources.filter((s) => s.name.toLowerCase().includes(mentionQuery.toLowerCase()))
    : [];

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setInput(val);
    const cursor = e.target.selectionStart || val.length;
    const textBeforeCursor = val.slice(0, cursor);
    const atIndex = textBeforeCursor.lastIndexOf("@");
    if (atIndex !== -1 && !textBeforeCursor.slice(atIndex).includes(" ")) {
      const q = textBeforeCursor.slice(atIndex + 1);
      setMentionQuery(q);
      setMentionIndex(atIndex);
    } else {
      setMentionQuery(null);
    }
  }

  function selectMention(sourceName: string) {
    if (mentionIndex === -1) return;
    const before = input.slice(0, mentionIndex);
    const after = input.slice(mentionIndex + (mentionQuery?.length || 0) + 1);
    const updated = `${before}@${sourceName} ${after}`;
    setInput(updated);
    setMentionQuery(null);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setMentionQuery(null);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      setMentionQuery(null);
      void sendMessage();
    }
  }

  const sourceCount = documents.length + datasets.length + mediaList.length;

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-[#faf9ef] text-[#24231f]">
      <GradientBackground className="fixed inset-0" />

      {/* Navbar */}
      <nav className="relative z-20 mx-auto mt-3 flex w-[min(100%-24px,880px)] items-center justify-between rounded-full border border-white/30 bg-black/80 px-3.5 py-2 shadow-lg backdrop-blur-xl sm:px-5 sm:py-2.5">
        <div className="flex items-center gap-2 sm:gap-3">
          <span className="text-sm font-bold tracking-tight text-white sm:text-lg">Emmaus AI</span>
          <span className="hidden h-3.5 w-px bg-white/20 sm:inline" />
          <span className="hidden text-xs text-white/50 sm:inline">Workspace</span>
        </div>
        <div className="flex items-center gap-1.5 sm:gap-2">
          <button
            type="button"
            onClick={() => setShowSources(!showSources)}
            className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/80 transition hover:bg-white/20 hover:text-white sm:px-3 sm:py-1.5 sm:text-xs"
          >
            {sourceCount} {sourceCount === 1 ? "source" : "sources"}
          </button>
          <button
            type="button"
            onClick={() => setClearModalOpen(true)}
            className="flex h-7 w-7 items-center justify-center rounded-full border border-red-400/25 bg-red-500/15 text-red-300 transition hover:bg-red-500/30 hover:text-white sm:h-8 sm:w-8"
            title="Clear all workspace sources and messages"
            aria-label="Clear workspace"
          >
            <Trash2 size={13} />
          </button>
          <button
            type="button"
            onClick={() => {
              // Clear stored workspace so home page always starts fresh
              localStorage.removeItem("vedax_workspace_id");
              router.push("/");
            }}
            className="rounded-full bg-white px-3 py-1 text-[11px] font-bold text-black transition hover:bg-white/90 sm:px-4 sm:py-1.5 sm:text-xs"
          >
            Home
          </button>
        </div>
      </nav>

      {/* Sources drawer */}
      {showSources && (
        <div className="fixed inset-x-0 top-20 z-30 mx-auto w-[min(100%-32px,880px)] rounded-2xl border border-white/20 bg-black/80 p-4 shadow-2xl backdrop-blur-2xl">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-white/70">Workspace Sources</h3>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-white/40">
                {documents.length} docs &middot; {datasets.length} datasets &middot; {mediaList.length} media
              </span>
              {sourceCount > 0 && (
                <button
                  type="button"
                  onClick={() => setClearModalOpen(true)}
                  className="flex h-6 w-6 items-center justify-center rounded-md border border-red-400/30 bg-red-500/20 text-red-300 hover:bg-red-500/35 hover:text-white transition"
                  title="Clear all workspace sources"
                  aria-label="Clear all sources"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          </div>
          <div className="max-h-60 space-y-2 overflow-y-auto pr-1">
            {/* Documents */}
            {documents.map((doc) => (
              <div key={doc.id} className="flex items-center justify-between rounded-xl bg-white/10 px-3 py-2 text-xs">
                <span className="truncate text-white/90 font-medium">📄 {doc.filename}</span>
                <span className="ml-2 shrink-0 text-white/40">{formatBytes(doc.size_bytes)}</span>
              </div>
            ))}
            {/* Datasets */}
            {datasets.map((ds) => (
              <div key={ds.id} className="flex items-center justify-between rounded-xl bg-white/10 px-3 py-2 text-xs">
                <span className="truncate text-white/90 font-medium">📊 {ds.filename}</span>
                <span className="ml-2 shrink-0 text-white/40">{ds.num_rows} rows</span>
              </div>
            ))}
            {/* Media (Images & Audio) */}
            {mediaList.map((m) => (
              <div key={m.id} className="flex items-center gap-3 rounded-xl bg-white/10 px-3 py-2 text-xs">
                {m.kind === "image" && m.url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={getMediaUrl(m.url)}
                    alt={m.filename}
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                    className="h-8 w-8 rounded-lg object-cover ring-1 ring-white/20 shrink-0"
                  />
                ) : (
                  <span className="text-base">{m.kind === "image" ? "🖼️" : "🎙️"}</span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-white/90 font-medium">{m.filename}</p>
                  {m.analysis && (
                    <p className="truncate text-[10px] text-white/50">
                      {typeof m.analysis === "string" ? m.analysis : JSON.stringify(m.analysis).slice(0, 50)}…
                    </p>
                  )}
                </div>
                <span className="shrink-0 text-white/40 text-[10px]">{formatBytes(m.size_bytes)}</span>
              </div>
            ))}
            {sourceCount === 0 && (
              <p className="py-4 text-center text-xs text-white/40">No sources uploaded in this workspace yet.</p>
            )}
          </div>
        </div>
      )}

      {/* Chat area */}
      <section className="relative z-10 mx-auto flex h-[calc(100svh-90px)] max-w-5xl flex-col px-4 pb-4 sm:px-8">
        {gone ? (
          <div className="flex flex-1 items-center justify-center pb-10">
            <div className="w-full max-w-md rounded-3xl border border-black/[.06] bg-white/70 p-8 text-center shadow-xl backdrop-blur-xl">
              <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-amber-500/15 text-amber-600">
                <AlertTriangle size={22} />
              </div>
              <h2 className="text-lg font-bold">Workspace not found</h2>
              <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-[#655f59]">
                This workspace was deleted or belongs to another session. Your stored reference was cleared automatically.
              </p>
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  onClick={() => router.push("/")}
                  className="rounded-full bg-[#282521] px-5 py-2 text-xs font-semibold text-white shadow-md transition hover:bg-black"
                >
                  Go Home
                </button>
                <button
                  onClick={async () => {
                    try {
                      await ensureAnonymousSession();
                      const ws = await apiFetch<Workspace>("/api/workspaces", {
                        method: "POST",
                        body: JSON.stringify({ name: "New Workspace" }),
                      });
                      localStorage.setItem("vedax_workspace_id", ws.id);
                      router.push(`/workspace/${ws.id}`);
                    } catch (e) {
                      console.error("createWorkspace failed:", e);
                    }
                  }}
                  className="rounded-full border border-black/[.1] bg-white/70 px-5 py-2 text-xs font-semibold transition hover:bg-white"
                >
                  New workspace
                </button>
              </div>
            </div>
          </div>
        ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto pt-4 pb-2">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[#655f59]">
              Ask a question about your sources
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((msg, i) => (
                <div key={i} className={`flex w-full ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "max-w-[86%] sm:max-w-xl rounded-2xl rounded-tr-sm bg-[#1c1917] text-white px-4 py-3 shadow-sm"
                        : "w-full max-w-[96%] sm:max-w-3xl rounded-2xl rounded-tl-sm border border-black/[.08] bg-white/80 px-4 py-3.5 text-[#24231f] shadow-sm backdrop-blur-md"
                    }`}
                  >
                    {msg.role === "assistant" && i === messages.length - 1 && streaming && (
                      <AgentPipelineTracker
                        activeNode={activeNode}
                        history={pipelineEvents}
                        streaming={streaming}
                        confidence={msg.confidence}
                      />
                    )}

                    {msg.role === "assistant" && !msg.content ? (
                      <LoadingState label="Investigating sources" />
                    ) : msg.role === "assistant" ? (
                      <ReactMarkdown
                        components={{
                          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                          strong: ({ children }) => <strong className="font-semibold text-black">{children}</strong>,
                          em: ({ children }) => <em className="text-[#514c47]">{children}</em>,
                          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
                          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
                          li: ({ children }) => <li className="pl-0.5">{children}</li>,
                          h1: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h3>,
                          h2: ({ children }) => <h3 className="mb-2 mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
                          h3: ({ children }) => <h3 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
                        }}
                      >
                        {cleanAssistantContent(msg.content)}
                      </ReactMarkdown>
                    ) : (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    )}
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-black/[.06] pt-2">
                        {msg.citations.map((citation, ci) => (
                          <button
                            key={`${citation.chunk_id}-${ci}`}
                            onClick={() => setSelectedCitation(citation)}
                            className="group flex items-center gap-1 rounded-full bg-black/[.05] px-2.5 py-1 text-[11px] text-[#655f59] transition hover:bg-[#6366f1]/10 hover:text-[#4338ca]"
                            title="Click to view full context passage"
                          >
                            <span className="font-semibold text-black/60 group-hover:text-[#4338ca]">Source {ci + 1}:</span>
                            <span className="truncate max-w-[140px]">{citation.document_name}</span>
                            {citation.page ? <span className="opacity-70">p.{citation.page}</span> : null}
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.charts && msg.charts.length > 0 && (
                      <div className="mt-3 space-y-3">
                        {msg.charts.map((chart, ci) => (
                          <ChartViewer key={ci} chart={chart} />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="shrink-0 pt-2 pb-1">
          <div className="w-full rounded-[24px] border border-white/50 bg-white/40 p-1.5 shadow-[0_8px_40px_rgba(77,63,54,.12)] backdrop-blur-xl">
            <div className="rounded-[20px] border border-black/[.06] bg-[#fffdf8]/80 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,.9)]">
              {/* Floating @ mention suggestions */}
              {matchingSources.length > 0 && (
                <div className="mb-2 max-h-36 overflow-y-auto rounded-xl border border-black/[.08] bg-white p-1 shadow-lg backdrop-blur-md">
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                    Mention a source
                  </div>
                  {matchingSources.map((source, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => selectMention(source.name)}
                      className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition hover:bg-black/[.05]"
                    >
                      <span>{source.type === "document" ? "📄" : source.type === "dataset" ? "📊" : "🖼️"}</span>
                      <span className="truncate font-medium text-gray-800">{source.name}</span>
                      <span className="ml-auto text-[10px] text-gray-400 capitalize">{source.type}</span>
                    </button>
                  ))}
                </div>
              )}

              {/* File chips with progress — shared with Home */}
              <AttachmentChips
                files={pendingFiles}
                progress={chipProgress}
                onRemove={removeChip}
                canRemove={!streaming}
              />

              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question… (type @ to reference a doc or dataset)"
                rows={1}
                className="min-h-10 w-full resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-[#8d8780]"
              />
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={streaming}
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-[#5f5953] transition hover:bg-black/[.06] disabled:opacity-40"
                    title="Attach file"
                    aria-label="Attach file"
                  >
                    <Paperclip size={14} />
                    <span className="hidden sm:inline">Attach</span>
                  </button>
                  <button
                    onClick={() => setShowCamera(true)}
                    disabled={streaming}
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-[#5f5953] transition hover:bg-black/[.06]"
                    title="Capture from camera"
                    aria-label="Capture from camera"
                  >
                    <Camera size={14} />
                    <span className="hidden sm:inline">Camera</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowVoiceModal(true)}
                    disabled={streaming}
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-[#5f5953] transition hover:bg-black/[.06]"
                    title="Voice input (Live recording or audio file)"
                    aria-label="Voice input"
                  >
                    <Mic size={14} />
                    <span className="hidden sm:inline">Voice</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowImageGenerator(true)}
                    disabled={streaming}
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs text-[#5f5953] transition hover:bg-black/[.06]"
                    title="Generate image with AI"
                    aria-label="Generate image"
                  >
                    <Sparkles size={14} />
                    <span className="hidden sm:inline">Image Gen</span>
                  </button>
                </div>
                  <button
                    onClick={() => void sendMessage()}
                    aria-label="Send message"
                    disabled={(!input.trim() && pendingFiles.length === 0) || streaming}
                  className="grid h-8 w-8 place-items-center rounded-full bg-[#282521] text-white shadow-md transition hover:-translate-y-0.5 hover:bg-black disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {streaming ? (
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/35 border-t-white" />
                  ) : (
                    <ArrowUp size={16} />
                  )}
                </button>
              </div>
            </div>
          </div>
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,image/*,audio/*"
            onChange={handleFileSelect}
          />
        </div>
        </div>
        )}
      </section>

      {showCamera && (
        <CameraCapture
          onCapture={(blob, filename) => {
            setShowCamera(false);
            void addWorkspaceFiles([new File([blob], filename, { type: blob.type || "image/jpeg" })]);
          }}
          onClose={() => setShowCamera(false)}
        />
      )}

      {showVoiceModal && (
        <VoiceRecordModal
          isOpen={showVoiceModal}
          onClose={() => setShowVoiceModal(false)}
          onAudioReady={(file) => {
            void addWorkspaceFiles([file]);
          }}
        />
      )}

      {showImageGenerator && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg h-[80vh] rounded-2xl border border-black/[.08] bg-[#fffdfa] shadow-2xl overflow-hidden">
            <ImageGenerator
              workspaceId={wsId}
              onClose={() => setShowImageGenerator(false)}
            />
          </div>
        </div>
      )}

      {/* Citation Inspector Drawer */}
      <CitationDrawer citation={selectedCitation} onClose={() => setSelectedCitation(null)} />

      {/* Clear Workspace Data Modal */}
      {clearModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md rounded-2xl border border-black/[.08] bg-[#fffdfa] p-6 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-red-100 text-red-600">
                <Trash2 size={20} />
              </div>
              <div>
                <h3 className="text-base font-semibold text-[#1c1917]">Clear Workspace Data?</h3>
                <p className="text-xs text-[#78716c]">Immediate and permanent removal</p>
              </div>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-[#57534e]">
              All documents, datasets, vector chunks, and conversation history in this workspace will be deleted. The workspace remains ready for fresh uploads.
            </p>
            <div className="mt-6 flex items-center justify-end gap-2">
              <button
                onClick={() => setClearModalOpen(false)}
                disabled={clearing}
                className="rounded-xl px-4 py-2 text-xs font-medium text-[#78716c] transition hover:bg-black/[.05] hover:text-black"
              >
                Cancel
              </button>
              <button
                onClick={handleClearWorkspace}
                disabled={clearing}
                className="flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-xs font-semibold text-white shadow transition hover:bg-red-700 disabled:opacity-50"
              >
                <Trash2 size={13} />
                <span>{clearing ? "Clearing..." : "Yes, Clear Data"}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

function cleanAssistantContent(content: string): string {
  return content
    // Remove OpenAI / GPT-OSS citation tokens like 【1†L2-L3】, 【4†source】, 【1】, etc.
    .replace(/【[^】]*】/g, "")
    .replace(/\[\d+†[^\]]*\]/g, "")
    .replace(/\[\^?\d+(?:\s*,\s*\^?\d+)*\]/g, "")
    .replace(/^\s*Confidence:\s*.*$/gim, "")
    .replace(/[—–]/g, "-")
    .replace(/\u00a0/g, " ")
    // GPT-OSS emits narrow/thin Unicode spaces (U+202F etc.) that break
    // copy-paste search and look inconsistent in the chat view.
    .replace(/[\u202f\u2009\u2007\u2002\u2003\u2005\u205f]/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
