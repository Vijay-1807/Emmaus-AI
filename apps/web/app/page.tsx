"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ensureAnonymousSession, apiFetch } from "@/lib/api";
import type { Workspace } from "@/lib/types";

export default function LandingPage() {
  const router = useRouter();

  async function launchWorkspace() {
    await ensureAnonymousSession();
    try {
      const workspace = await apiFetch<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: "My Workspace", description: "Anonymous session" }),
      });
      router.push(`/workspace/${workspace.id}`);
    } catch {
      router.push("/dashboard");
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex items-center justify-between px-8 py-5 border-b border-border">
        <div className="text-xl font-bold tracking-tight">VedaX AI</div>
        <div className="flex gap-3">
          <Link href="/login" className="px-4 py-2 text-sm text-text-muted hover:text-text transition-colors">Sign in</Link>
          <button onClick={launchWorkspace} className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors">Get started</button>
        </div>
      </header>
      <main className="flex-1 flex flex-col items-center justify-center px-8">
        <div className="max-w-2xl text-center">
          <h1 className="text-5xl font-bold tracking-tight mb-6">
            Investigate information across{" "}
            <span className="text-primary">every modality</span>
          </h1>
          <p className="text-lg text-text-muted mb-10 leading-relaxed">
            Upload documents, datasets, images, handwritten pages, or audio.
            Ask a question. VedaX AI combines RAG, data analysis, vision, OCR,
            and agentic reasoning to produce evidence-backed answers with
            visualizations and reports.
          </p>
          <div className="flex gap-4 justify-center">
            <button onClick={launchWorkspace} className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors font-medium">
              Launch workspace
            </button>
            <a href="https://github.com/Vijay-1807/Veda-ai" target="_blank" rel="noreferrer" className="px-6 py-3 border border-border rounded-lg hover:border-border-active transition-colors text-text-muted">
              View on GitHub
            </a>
          </div>
          <p className="mt-4 text-xs text-text-muted">No login required. Start immediately.</p>
        </div>
        <div className="mt-20 w-full max-w-4xl border border-border rounded-xl bg-surface p-1 opacity-60">
          <div className="flex gap-1 text-xs text-text-muted p-3 border-b border-border">
            <span className="w-3 h-3 rounded-full bg-error/60 inline-block" />
            <span className="w-3 h-3 rounded-full bg-warning/60 inline-block" />
            <span className="w-3 h-3 rounded-full bg-success/60 inline-block" />
          </div>
          <div className="grid grid-cols-12 gap-px bg-border">
            <div className="col-span-3 bg-surface-2 p-4 text-xs space-y-2">
              <div className="font-medium text-text-muted mb-3">SOURCES</div>
              <div className="p-2 rounded bg-bg border border-border">Q3-report.pdf</div>
              <div className="p-2 rounded bg-bg border border-border">Sales.xlsx</div>
              <div className="p-2 rounded bg-bg border border-border">Chart.png</div>
              <div className="p-2 rounded bg-bg border border-border">Notes.jpg</div>
            </div>
            <div className="col-span-6 bg-surface p-4 text-xs">
              <div className="font-medium text-text-muted mb-3">INVESTIGATION</div>
              <div className="text-text text-sm">Why did revenue fall?</div>
              <div className="mt-4 text-text-muted leading-relaxed">
                Revenue fell 14.2% in Q3. The main driver was the South region
                which declined 23% due to market conditions. [1][2]
              </div>
              <div className="mt-4 p-3 rounded bg-bg border border-border text-text-muted">
                [chart placeholder]
              </div>
            </div>
            <div className="col-span-3 bg-surface-2 p-4 text-xs space-y-2">
              <div className="font-medium text-text-muted mb-3">EVIDENCE</div>
              <div className="p-2 rounded bg-bg border border-border">
                <div className="text-text">Q3.pdf p.12</div>
                <div className="text-text-muted mt-1">Revenue fell 14.2%</div>
              </div>
              <div className="p-2 rounded bg-bg border border-border">
                <div className="text-text">Sales.xlsx</div>
                <div className="text-text-muted mt-1">South region -23%</div>
              </div>
              <div className="mt-4 p-2 rounded bg-success/10 border border-success/20 text-center">
                <div className="text-success font-medium">91%</div>
                <div className="text-text-muted">confidence</div>
              </div>
            </div>
          </div>
        </div>
      </main>
      <footer className="px-8 py-4 text-center text-xs text-text-muted border-t border-border">
        VedaX AI &mdash; Multimodal Agentic Knowledge &amp; Analysis Platform
      </footer>
    </div>
  );
}
