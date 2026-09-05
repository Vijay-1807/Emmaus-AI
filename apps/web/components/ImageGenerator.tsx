"use client";

import { useState, useRef } from "react";
import { Sparkles, Download, RefreshCw, Loader2, X } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface ImageGeneratorProps {
  workspaceId: string;
  onClose?: () => void;
}

interface GeneratedImage {
  url: string;
  mime: string;
  metadata?: Record<string, unknown>;
}

export default function ImageGenerator({ workspaceId, onClose }: ImageGeneratorProps) {
  const [prompt, setPrompt] = useState("");
  const [steps, setSteps] = useState(4);
  const [seed, setSeed] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedImage, setGeneratedImage] = useState<GeneratedImage | null>(null);
  const [history, setHistory] = useState<GeneratedImage[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  async function handleGenerate() {
    if (!prompt.trim() || loading) return;

    setLoading(true);
    setError(null);
    setGeneratedImage(null);

    try {
      const payload: Record<string, unknown> = {
        prompt: prompt.trim(),
        steps,
      };

      if (seed.trim()) {
        const seedNum = parseInt(seed.trim(), 10);
        if (!isNaN(seedNum)) {
          payload.seed = seedNum;
        }
      }

      const result = await apiFetch<{ success: boolean; image: string; mime: string; error?: string; metadata?: Record<string, unknown> }>(
        `/api/image/generate?workspace_id=${workspaceId}`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      if (!result.success || !result.image) {
        throw new Error(result.error || "Failed to generate image");
      }

      const newImage: GeneratedImage = {
        url: result.image,
        mime: result.mime,
        metadata: result.metadata,
      };

      setGeneratedImage(newImage);
      setHistory((prev) => [newImage, ...prev].slice(0, 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image generation failed");
    } finally {
      setLoading(false);
    }
  }

  function handleDownload() {
    if (!generatedImage) return;

    const link = document.createElement("a");
    link.href = generatedImage.url;
    link.download = `emmaus-generated-${Date.now()}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function handleRegenerate() {
    setSeed(Math.floor(Math.random() * 999999).toString());
    handleGenerate();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-black/[.08] px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-indigo-500" />
          <h3 className="text-sm font-semibold text-[#1c1917]">Image Generation</h3>
          <span className="text-xs text-[#78716c]">FLUX.1 Schnell</span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-black/[.05] transition"
            aria-label="Close"
          >
            <X size={16} className="text-[#78716c]" />
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Prompt Input */}
        <div>
          <label className="block text-xs font-medium text-[#78716c] mb-1.5">
            Prompt
          </label>
          <textarea
            ref={inputRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="A cinematic futuristic city at sunset..."
            className="w-full h-24 px-3 py-2 text-sm rounded-xl border border-black/[.08] bg-white/80 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/40 resize-none placeholder:text-[#a8a29e]"
            disabled={loading}
          />
          <p className="mt-1 text-xs text-[#a8a29e]">
            {prompt.length}/2048 characters
          </p>
        </div>

        {/* Parameters */}
        <div className="flex gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-[#78716c] mb-1.5">
              Steps (1-8)
            </label>
            <input
              type="number"
              min={1}
              max={8}
              value={steps}
              onChange={(e) => setSteps(Math.max(1, Math.min(8, parseInt(e.target.value) || 4)))}
              className="w-full px-3 py-2 text-sm rounded-xl border border-black/[.08] bg-white/80 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/40"
              disabled={loading}
            />
          </div>
          <div className="flex-1">
            <label className="block text-xs font-medium text-[#78716c] mb-1.5">
              Seed (optional)
            </label>
            <input
              type="text"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="Random"
              className="w-full px-3 py-2 text-sm rounded-xl border border-black/[.08] bg-white/80 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500/40 placeholder:text-[#a8a29e]"
              disabled={loading}
            />
          </div>
        </div>

        {/* Generate Button */}
        <button
          onClick={handleGenerate}
          disabled={!prompt.trim() || loading}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-500 text-white text-sm font-medium hover:bg-indigo-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Sparkles size={16} />
              Generate Image
            </>
          )}
        </button>

        {/* Error */}
        {error && (
          <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* Generated Image */}
        {generatedImage && (
          <div className="space-y-3">
            <div className="relative rounded-xl overflow-hidden border border-black/[.08] bg-white/80">
              <img
                src={generatedImage.url}
                alt={prompt}
                className="w-full h-auto object-contain max-h-96"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleDownload}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-xl border border-black/[.08] bg-white/80 text-sm font-medium hover:bg-black/[.03] transition"
              >
                <Download size={14} />
                Download
              </button>
              <button
                onClick={handleRegenerate}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-xl border border-black/[.08] bg-white/80 text-sm font-medium hover:bg-black/[.03] transition"
              >
                <RefreshCw size={14} />
                Regenerate
              </button>
            </div>
            {generatedImage.metadata && (
              <div className="text-xs text-[#a8a29e] text-center">
                Model: {String(generatedImage.metadata.model || "FLUX.1")} | 
                Steps: {String(generatedImage.metadata.steps || steps)}
                {generatedImage.metadata.seed ? ` | Seed: ${String(generatedImage.metadata.seed)}` : ""}
              </div>
            )}
          </div>
        )}

        {/* History */}
        {history.length > 1 && (
          <div>
            <h4 className="text-xs font-medium text-[#78716c] mb-2">Recent Generations</h4>
            <div className="flex gap-2 overflow-x-auto pb-2">
              {history.slice(1, 6).map((img, idx) => (
                <button
                  key={idx}
                  onClick={() => setGeneratedImage(img)}
                  className="flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden border border-black/[.08] hover:border-indigo-500/40 transition"
                >
                  <img
                    src={img.url}
                    alt={`Generated ${idx + 1}`}
                    className="w-full h-full object-cover"
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
