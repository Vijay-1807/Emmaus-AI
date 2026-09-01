"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import AppLayout from "@/components/AppLayout";
import CameraCapture from "@/components/CameraCapture";
import { apiFetch, sseUrl, getToken } from "@/lib/api";
import type { Document, Dataset, Citation, Chart, Evidence } from "@/lib/types";
import { formatDate, formatBytes } from "@/lib/utils";

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
  const wsId = params.id as string;
  const [documents, setDocuments] = useState<Document[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence[]>([]);
  const [showCamera, setShowCamera] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!wsId) return;
    apiFetch<Document[]>(`/api/documents?workspace_id=${wsId}`).then(setDocuments).catch(() => {});
    apiFetch<Dataset[]>(`/api/datasets?workspace_id=${wsId}`).then(setDatasets).catch(() => {});
  }, [wsId]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(scrollToBottom, [messages, scrollToBottom]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);

    try {
      const token = getToken();
      const res = await fetch(sseUrl("/api/chat/stream"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ workspace_id: wsId, message: text }),
      });

      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantContent = "";
      let assistantCitations: Citation[] = [];
      let assistantCharts: Chart[] = [];
      let assistantEvidence: Evidence[] = [];
      let confidence: number | null = null;

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
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
            if (event.type === "token") {
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
              setSelectedEvidence(assistantEvidence);
            } else if (event.type === "done") {
              const inv = event.investigation;
              if (inv) {
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
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Connection failed"}`,
        };
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <AppLayout>
      <div className="h-screen flex flex-col">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
          <h1 className="text-sm font-medium">Workspace</h1>
          <div className="flex gap-4 text-xs text-text-muted">
            <span>{documents.length} docs</span>
            <span>{datasets.length} datasets</span>
          </div>
        </div>

        <div className="flex flex-1 min-h-0">
          <div className="w-56 border-r border-border bg-surface overflow-y-auto shrink-0">
            <div className="p-3">
              <h3 className="text-xs font-medium text-text-muted mb-2">SOURCES</h3>
              {documents.map((doc) => (
                <div key={doc.id} className="p-2 rounded bg-bg border border-border mb-1.5 text-xs">
                  <div className="truncate text-text">{doc.filename}</div>
                  <div className="text-text-muted mt-0.5">{doc.source_type} &middot; {formatBytes(doc.size_bytes)}</div>
                </div>
              ))}
              {datasets.map((ds) => (
                <div key={ds.id} className="p-2 rounded bg-bg border border-border mb-1.5 text-xs">
                  <div className="truncate text-text">{ds.filename}</div>
                  <div className="text-text-muted mt-0.5">{ds.num_rows} rows</div>
                </div>
              ))}
              {documents.length === 0 && datasets.length === 0 && (
                <p className="text-xs text-text-muted">No sources yet</p>
              )}
            </div>
          </div>

          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 && (
                <div className="flex items-center justify-center h-full text-text-muted text-sm">
                  Ask a question about your sources
                </div>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={`max-w-3xl ${msg.role === "assistant" ? "" : "ml-auto"}`}>
                  <div
                    className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "bg-primary/10 text-text ml-auto max-w-lg"
                        : "bg-surface border border-border text-text"
                    }`}
                  >
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                    {msg.charts && msg.charts.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {msg.charts.map((chart, ci) => (
                          <div key={ci} className="bg-bg border border-border rounded-lg p-3">
                            <div className="text-xs font-medium text-text-muted mb-1">{chart.title}</div>
                            <div className="text-xs text-text-muted">
                              {chart.chart_type} chart &middot; {chart.labels.length} data points
                            </div>
                            <div className="mt-2 flex gap-1 items-end h-16">
                              {chart.series[0]?.values.slice(0, 12).map((v, vi) => (
                                <div
                                  key={vi}
                                  className="bg-primary/60 rounded-t min-w-[4px] flex-1"
                                  style={{ height: `${Math.max(4, (v / Math.max(...(chart.series[0]?.values || [1]))) * 100)}%` }}
                                  title={`${chart.labels[vi]}: ${v}`}
                                />
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {msg.confidence != null && (
                      <div className="mt-2 text-xs text-text-muted">
                        Confidence: {Math.round(msg.confidence * 100)}%
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-4 border-t border-border shrink-0">
              <div className="flex gap-2 max-w-3xl mx-auto items-end">
                <button
                  onClick={() => setShowCamera(true)}
                  className="px-3 py-2.5 bg-surface border border-border rounded-xl text-text-muted hover:text-text hover:border-border-active transition-colors text-sm shrink-0"
                  title="Capture from camera"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
                    <circle cx="12" cy="13" r="4"/>
                  </svg>
                </button>
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a question..."
                  rows={1}
                  className="flex-1 px-4 py-2.5 bg-surface border border-border rounded-xl text-text text-sm resize-none focus:outline-none focus:border-primary"
                />
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || streaming}
                  className="px-4 py-2.5 bg-primary text-white rounded-xl text-sm hover:bg-primary-hover transition-colors disabled:opacity-50 shrink-0"
                >
                  {streaming ? "..." : "Send"}
                </button>
              </div>
            </div>
          </div>

          <div className="w-64 border-l border-border bg-surface overflow-y-auto shrink-0">
            <div className="p-3">
              <h3 className="text-xs font-medium text-text-muted mb-2">EVIDENCE</h3>
              {selectedEvidence.length === 0 ? (
                <p className="text-xs text-text-muted">No evidence yet</p>
              ) : (
                <div className="space-y-2">
                  {selectedEvidence.map((ev, i) => (
                    <div key={i} className="p-2 rounded bg-bg border border-border text-xs">
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          ev.kind === "document" ? "bg-primary" :
                          ev.kind === "data" ? "bg-success" :
                          ev.kind === "vision" ? "bg-warning" : "bg-error"
                        }`} />
                        <span className="text-text font-medium truncate">{ev.source_name}</span>
                      </div>
                      <div className="text-text-muted line-clamp-3">{ev.summary.slice(0, 200)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {showCamera && (
        <CameraCapture
          onCapture={async (blob, filename) => {
            setShowCamera(false);
            const formData = new FormData();
            formData.append("file", blob, filename);
            formData.append("workspace_id", wsId);
            try {
              const token = getToken();
              const uploaded = await fetch("/api/media/upload", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
                body: formData,
              }).then((r) => r.json());
              setMessages((prev) => [
                ...prev,
                { role: "user", content: `[Captured image: ${filename}]` },
              ]);
              setInput("");
              setStreaming(true);
              const res = await fetch(sseUrl("/api/chat/stream"), {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  workspace_id: wsId,
                  message: `Analyze this captured image: ${uploaded.url || uploaded.media_id}`,
                }),
              });
              const reader = res.body?.getReader();
              if (reader) {
                const decoder = new TextDecoder();
                let buffer = "";
                let assistantContent = "";
                setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) break;
                  buffer += decoder.decode(value, { stream: true });
                  const lines = buffer.split("\n");
                  buffer = lines.pop() || "";
                  for (const line of lines) {
                    if (line.startsWith("data: ")) {
                      try {
                        const evt = JSON.parse(line.slice(6));
                        if (evt.type === "token") {
                          assistantContent += evt.content;
                          setMessages((prev) => {
                            const updated = [...prev];
                            updated[updated.length - 1] = { role: "assistant", content: assistantContent };
                            return updated;
                          });
                        } else if (evt.type === "done") {
                          setMessages((prev) => {
                            const updated = [...prev];
                            updated[updated.length - 1] = {
                              role: "assistant",
                              content: assistantContent || evt.answer || "Analysis complete.",
                              citations: evt.citations,
                              charts: evt.charts,
                              evidence: evt.evidence,
                              confidence: evt.confidence,
                            };
                            return updated;
                          });
                          if (evt.evidence) setSelectedEvidence(evt.evidence);
                        }
                      } catch {}
                    }
                  }
                }
              }
            } catch (err) {
              setMessages((prev) => [...prev, { role: "assistant", content: `Upload failed: ${err}` }]);
            }
            setStreaming(false);
          }}
          onClose={() => setShowCamera(false)}
        />
      )}
    </AppLayout>
  );
}
