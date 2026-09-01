"use client";

import AppLayout from "@/components/AppLayout";

export default function SettingsPage() {
  return (
    <AppLayout>
      <div className="p-8 max-w-2xl">
        <h1 className="text-2xl font-bold mb-2">Settings</h1>
        <p className="text-text-muted text-sm mb-8">Configure models, workspace, and integrations</p>

        <div className="space-y-6">
          <section className="bg-surface border border-border rounded-xl p-5">
            <h2 className="font-medium mb-3">Model Providers</h2>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Ollama (Primary LLM)</span>
                <span className="text-success text-xs">gpt-oss:120b</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Ollama (Vision)</span>
                <span className="text-success text-xs">gemma4:31b</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Groq (Fast)</span>
                <span className="text-success text-xs">llama-3.1-8b-instant</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Groq (Rerank)</span>
                <span className="text-success text-xs">llama-3.3-70b-versatile</span>
              </div>
              <div className="flex items-center justify-between py-2">
                <span className="text-text-muted">Embedding</span>
                <span className="text-success text-xs">gemini-embedding-001 (3072d)</span>
              </div>
            </div>
          </section>

          <section className="bg-surface border border-border rounded-xl p-5">
            <h2 className="font-medium mb-3">Retrieval</h2>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Vector search top-k</span>
                <span className="text-text">30</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Lexical search top-k</span>
                <span className="text-text">30</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Final top-k</span>
                <span className="text-text">6</span>
              </div>
              <div className="flex items-center justify-between py-2">
                <span className="text-text-muted">RRF k</span>
                <span className="text-text">60</span>
              </div>
            </div>
          </section>

          <section className="bg-surface border border-border rounded-xl p-5">
            <h2 className="font-medium mb-3">Storage</h2>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-text-muted">Media storage</span>
                <span className="text-text">Cloudinary</span>
              </div>
              <div className="flex items-center justify-between py-2">
                <span className="text-text-muted">Database</span>
                <span className="text-text">MongoDB Atlas</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
