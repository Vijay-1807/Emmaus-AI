"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import PageShell from "@/components/PageShell";
import EvaluationPanel from "@/components/EvaluationPanel";
import ObservabilityPanel from "@/components/ObservabilityPanel";
import { apiFetch } from "@/lib/api";
import { useWorkspaceId } from "@/lib/useWorkspaceId";
import { formatBytes } from "@/lib/utils";
import { Trash2, AlertTriangle, RefreshCw, HardDrive } from "lucide-react";
import { cn } from "@/lib/utils";

interface StorageSummary {
  workspace_id: string;
  documents: { count: number; size_bytes: number };
  datasets: { count: number; size_bytes: number; row_count: number };
  media: { count: number };
  chat: { conversations: number; messages: number };
  total_size_bytes: number;
}

interface ProviderInfo {
  available: boolean;
  default_model: string;
  fast_model?: string;
  vision_model?: string;
}

interface HealthInfo {
  status: string;
  environment: string;
  providers: {
    providers: Record<string, ProviderInfo>;
    routing: { reasoning: string; fast_tasks: string; vision: string };
  };
  storage?: {
    mode: string;
    cloudinary_configured: boolean;
    cloudinary_usable: boolean;
  };
  telegram?: { configured: boolean };
}

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "models", label: "Models" },
  { key: "evaluation", label: "Evaluation" },
  { key: "observability", label: "Observability" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function isTab(value: string | null): value is TabKey {
  return TABS.some((t) => t.key === value);
}

export default function SettingsPage() {
  return (
    <PageShell>
      <Suspense fallback={<div className="py-10 text-center text-sm text-[#655f59]">Loading settings…</div>}>
        <SettingsContent />
      </Suspense>
    </PageShell>
  );
}

function SettingsContent() {
  const searchParams = useSearchParams();
  const initial = searchParams.get("tab");
  const [tab, setTab] = useState<TabKey>(isTab(initial) ? initial : "overview");
  const { wsId: workspaceId } = useWorkspaceId();
  const [storage, setStorage] = useState<StorageSummary | null>(null);
  const [loadingStorage, setLoadingStorage] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);

  // Live model routing from the backend — never goes stale like hardcoded names.
  useEffect(() => {
    if (tab !== "models" || health) return;
    apiFetch<HealthInfo>("/api/health").then(setHealth).catch(() => {});
  }, [tab, health]);

  useEffect(() => {
    if (workspaceId) {
      loadStorage(workspaceId);
    } else {
      setStorage(null);
    }
  }, [workspaceId]);

  async function loadStorage(wsId: string) {
    setLoadingStorage(true);
    try {
      const data = await apiFetch<StorageSummary>(`/api/workspaces/${wsId}/storage-summary`);
      setStorage(data);
    } catch (err) {
      console.warn("Storage summary unavailable:", err);
    } finally {
      setLoadingStorage(false);
    }
  }

  async function handleClearWorkspace() {
    if (!workspaceId || clearing) return;
    if (!confirm("Are you sure you want to clear all documents, datasets, and chat history in this workspace? This cannot be undone.")) return;
    setClearing(true);
    setMessage(null);
    try {
      await apiFetch(`/api/workspaces/${workspaceId}/clear`, { method: "POST" });
      setMessage({ type: "success", text: "Workspace storage cleared successfully!" });
      loadStorage(workspaceId);
    } catch (err) {
      setMessage({ type: "error", text: `Failed to clear storage: ${err instanceof Error ? err.message : err}` });
    } finally {
      setClearing(false);
    }
  }

  async function handleFactoryReset() {
    if (resetting) return;
    if (!confirm("FACTORY RESET: This will clear all local session tokens, workspaces, and cached data, giving you a completely clean slate. Proceed?")) return;
    setResetting(true);
    try {
      if (workspaceId) {
        await apiFetch(`/api/workspaces/${workspaceId}/clear`, { method: "POST" }).catch(() => {});
      }
      localStorage.clear();
      sessionStorage.clear();
      setMessage({ type: "success", text: "Reset complete! Re-initializing session..." });
      setTimeout(() => {
        window.location.href = "/";
      }, 1000);
    } catch {
      setMessage({ type: "error", text: "Reset failed." });
      setResetting(false);
    }
  }

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-[#655f59]">Storage, models, benchmarks, and observability</p>
      </div>

      {/* Tabs — scrollable on mobile */}
      <div className="mb-6 flex gap-1 overflow-x-auto rounded-full border border-black/[.06] bg-white/50 p-1 backdrop-blur">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "flex-1 whitespace-nowrap rounded-full px-4 py-2 text-xs font-semibold transition",
              tab === t.key
                ? "bg-[#282521] text-white shadow-md"
                : "text-[#655f59] hover:bg-black/[.05] hover:text-black"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {message && (
        <div
          className={`mb-6 rounded-2xl border p-4 text-xs font-medium backdrop-blur ${
            message.type === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700"
              : "border-red-500/30 bg-red-500/10 text-red-700"
          }`}
        >
          {message.text}
        </div>
      )}

      {tab === "overview" && (
        <section className="rounded-2xl border border-black/[.06] bg-white/60 p-5 backdrop-blur">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <HardDrive size={18} className="text-[#6366f1]" />
              <h2 className="font-semibold text-base">Storage &amp; Retention</h2>
            </div>
            <button
              onClick={() => workspaceId && loadStorage(workspaceId)}
              disabled={loadingStorage}
              className="flex items-center gap-1 text-xs text-[#655f59] hover:text-black"
            >
              <RefreshCw size={12} className={loadingStorage ? "animate-spin" : ""} />
              <span>Refresh</span>
            </button>
          </div>

          <p className="text-xs text-[#655f59] mb-4">
            Control your workspace data on demand. Rather than arbitrary auto-deletions, you have full control to clear workspace assets or perform a full factory reset.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
            <div className="rounded-xl border border-black/[.06] bg-white/60 p-3">
              <span className="text-[11px] text-[#8d8780]">Documents</span>
              <div className="text-base font-bold mt-0.5">{storage ? storage.documents.count : 0}</div>
              <span className="text-[10px] text-[#8d8780]">{storage ? formatBytes(storage.documents.size_bytes ?? 0) : "0 B"}</span>
            </div>
            <div className="rounded-xl border border-black/[.06] bg-white/60 p-3">
              <span className="text-[11px] text-[#8d8780]">Datasets</span>
              <div className="text-base font-bold mt-0.5">{storage ? storage.datasets.count : 0}</div>
              <span className="text-[10px] text-[#8d8780]">{storage ? `${storage.datasets.row_count ?? 0} rows` : "0 rows"}</span>
            </div>
            <div className="rounded-xl border border-black/[.06] bg-white/60 p-3">
              <span className="text-[11px] text-[#8d8780]">Conversations</span>
              <div className="text-base font-bold mt-0.5">{storage ? storage.chat.conversations : 0}</div>
              <span className="text-[10px] text-[#8d8780]">{storage ? `${storage.chat.messages} msgs` : "0 msgs"}</span>
            </div>
            <div className="rounded-xl border border-black/[.06] bg-white/60 p-3">
              <span className="text-[11px] text-[#8d8780]">Total Footprint</span>
              <div className="text-base font-bold mt-0.5 text-[#6366f1]">{storage ? formatBytes(storage.total_size_bytes ?? 0) : "0 B"}</div>
              <span className="text-[10px] text-emerald-600 font-medium">Optimized</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-black/[.06] pt-4">
            <button
              onClick={handleClearWorkspace}
              disabled={clearing || !workspaceId}
              className="flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50/80 px-4 py-2 text-xs font-semibold text-rose-700 hover:bg-red-100 transition disabled:opacity-50"
            >
              <Trash2 size={13} />
              <span>{clearing ? "Clearing..." : "Clear Workspace Data"}</span>
            </button>
            <button
              onClick={handleFactoryReset}
              disabled={resetting}
              className="flex items-center gap-1.5 rounded-full border border-black/[.08] bg-white/60 px-4 py-2 text-xs font-semibold text-[#655f59] hover:text-black hover:bg-white/80 transition disabled:opacity-50"
            >
              <AlertTriangle size={13} className="text-amber-500" />
              <span>{resetting ? "Resetting..." : "Factory Reset (All Storage)"}</span>
            </button>
          </div>
        </section>
      )}

      {tab === "models" && (
        <div className="space-y-4">
          <section className="rounded-2xl border border-black/[.06] bg-white/60 p-5 backdrop-blur">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <h2 className="font-semibold text-base">Active Models &amp; Inference</h2>
              {health ? (
                <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-600">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                  Live · {health.environment}
                </span>
              ) : (
                <span className="rounded-full bg-black/[.05] px-2.5 py-0.5 text-[11px] font-semibold text-[#655f59]">Defaults shown · backend unreachable</span>
              )}
            </div>
            <div className="space-y-2 text-xs">
              <ModelRow
                label="Primary Reasoning LLM"
                route={routeModel(health, "reasoning", "openai/gpt-oss-120b")}
              />
              <ModelRow
                label="Fast Router & Classifier"
                route={routeModel(health, "fast_tasks", "openai/gpt-oss-20b")}
              />
              <ModelRow
                label="Vision OCR & Document Intelligence"
                route={routeModel(health, "vision", "qwen/qwen3.6-27b")}
              />
              <div className="flex flex-col gap-0.5 py-2 border-b border-black/[.06] sm:flex-row sm:items-center sm:justify-between">
                <span className="text-[#655f59]">Speech-to-Text (STT)</span>
                <div className="flex flex-col sm:items-end gap-0.5">
                  <span className="font-mono font-semibold text-[11px]">nova-3 <span className="text-[#8d8780] font-normal">(Deepgram · Primary)</span></span>
                  <span className="font-mono text-[#8d8780] text-[10px]">saaras:v4 (Sarvam · Fallback)</span>
                  <span className="font-mono text-[#8d8780] text-[10px]">whisper-large-v3-turbo (Groq · Final)</span>
                </div>
              </div>
              <div className="flex flex-col gap-0.5 py-2 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-[#655f59]">Dense Embeddings</span>
                <span className="font-mono text-[#6366f1] font-semibold">Jina v5 Omni Small <span className="text-[#8d8780] font-normal">(1024D · Multimodal)</span></span>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-black/[.06] bg-white/60 p-5 backdrop-blur">
            <h2 className="font-semibold text-base mb-3">Hybrid Retrieval &amp; Cloud Storage</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="rounded-xl border border-black/[.06] bg-white/60 p-3 space-y-1.5">
                <div className="font-semibold">Hybrid RAG Pipeline</div>
                <div className="flex justify-between text-[#655f59]"><span>Vector Index:</span><span className="font-mono text-[#24231f]">Atlas $vectorSearch (1024D)</span></div>
                <div className="flex justify-between text-[#655f59]"><span>Lexical Index:</span><span className="font-mono text-[#24231f]">Atlas $search BM25</span></div>
                <div className="flex justify-between text-[#655f59]"><span>Fusion:</span><span className="font-mono text-[#24231f]">RRF (k=60, top-k=6)</span></div>
              </div>
              <div className="rounded-xl border border-black/[.06] bg-white/60 p-3 space-y-1.5">
                <div className="font-semibold">Cloud &amp; Bot Integrations</div>
                <div className="flex justify-between text-[#655f59]">
                  <span>Cloud Media:</span>
                  {health?.storage ? (
                    health.storage.cloudinary_usable ? (
                      <span className="font-mono text-emerald-600 font-semibold">Cloudinary CDN (Auto)</span>
                    ) : health.storage.cloudinary_configured ? (
                      <span className="font-mono text-amber-600 font-semibold" title="Key lacks upload permission — uploads fall back to local disk">Local fallback (key blocked)</span>
                    ) : (
                      <span className="font-mono text-[#24231f]">Local disk</span>
                    )
                  ) : (
                    <span className="font-mono text-[#8d8780]">Checking…</span>
                  )}
                </div>
                <div className="flex justify-between text-[#655f59]">
                  <span>Telegram Bot:</span>
                  {health?.telegram ? (
                    health.telegram.configured ? (
                      <span className="font-mono text-[#0088cc]">/api/telegram/webhook</span>
                    ) : (
                      <span className="font-mono text-[#8d8780]">Not configured</span>
                    )
                  ) : (
                    <span className="font-mono text-[#8d8780]">Checking…</span>
                  )}
                </div>
                <div className="flex justify-between text-[#655f59]"><span>Observability:</span><span className="font-mono text-[#24231f]">Langfuse Tracing</span></div>
              </div>
            </div>
          </section>
        </div>
      )}

      {tab === "evaluation" && (
        <section className="rounded-2xl border border-black/[.06] bg-white/60 p-5 backdrop-blur">
          <EvaluationPanel workspaceId={workspaceId} />
        </section>
      )}

      {tab === "observability" && (
        <section className="rounded-2xl border border-black/[.06] bg-white/60 p-5 backdrop-blur">
          <ObservabilityPanel workspaceId={workspaceId} />
        </section>
      )}
    </div>
  );
}

type RouteKey = "reasoning" | "fast_tasks" | "vision";

function routeModel(
  health: HealthInfo | null,
  route: RouteKey,
  fallback: string,
): { provider?: string; model: string } {
  const provider = health?.providers.routing[route];
  const info = provider ? health?.providers.providers[provider] : undefined;
  if (!info) return { provider, model: fallback };
  if (route === "fast_tasks" && info.fast_model) return { provider, model: info.fast_model };
  if (route === "vision" && info.vision_model) return { provider, model: info.vision_model };
  return { provider, model: info.default_model };
}

function ModelRow({
  label,
  route,
}: {
  label: string;
  route: { provider?: string; model: string };
}) {
  return (
    <div className="flex flex-col gap-0.5 py-2 border-b border-black/[.06] sm:flex-row sm:items-center sm:justify-between">
      <span className="text-[#655f59]">{label}</span>
      <span className="font-mono font-semibold">
        {route.model}{" "}
        {route.provider && (
          <span className="text-[#8d8780] font-normal">({route.provider})</span>
        )}
      </span>
    </div>
  );
}
