"use client";

import { useState, useRef, useEffect } from "react";
import { Sparkles, Download, RefreshCw, Loader2, X, ZoomIn } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface ImageGeneratorProps {
  workspaceId: string;
  onImageGenerated?: (imageUrl: string) => void;
}

interface GeneratedImage {
  url: string;
  mime: string;
  metadata?: Record<string, unknown>;
}

export default function ImageGenerator({ workspaceId, onImageGenerated }: ImageGeneratorProps) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedImage, setGeneratedImage] = useState<GeneratedImage | null>(null);
  const [history, setHistory] = useState<GeneratedImage[]>([]);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!lightboxImage) {
      setZoom(1);
      setPos({ x: 0, y: 0 });
    }
  }, [lightboxImage]);

  async function handleGenerate() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError(null);
    setGeneratedImage(null);
    try {
      const result = await apiFetch<{ success: boolean; image: string; mime: string; error?: string; metadata?: Record<string, unknown> }>(
        `/api/image/generate?workspace_id=${workspaceId}`,
        { method: "POST", body: JSON.stringify({ prompt: prompt.trim(), steps: 4 }) }
      );
      if (!result.success || !result.image) throw new Error(result.error || "Failed to generate image");
      const newImage: GeneratedImage = { url: result.image, mime: result.mime, metadata: result.metadata };
      setGeneratedImage(newImage);
      setHistory((prev) => [newImage, ...prev].slice(0, 10));
      onImageGenerated?.(result.image);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image generation failed");
    } finally {
      setLoading(false);
    }
  }

  function handleDownload(img: GeneratedImage) {
    const link = document.createElement("a");
    link.href = img.url;
    link.download = `emmaus-generated-${Date.now()}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  }

  function handleWheel(e: React.WheelEvent) {
    e.preventDefault();
    setZoom((z) => Math.min(5, Math.max(0.5, z + (e.deltaY > 0 ? -0.15 : 0.15))));
  }

  function handleMouseDown(e: React.MouseEvent) {
    if (zoom <= 1) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, startPosX: pos.x, startPosY: pos.y };
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setPos({ x: dragRef.current.startPosX + dx, y: dragRef.current.startPosY + dy });
  }

  function handleMouseUp() {
    dragRef.current = null;
  }

  return (
    <div className="w-full space-y-3">
      {/* Inline prompt input — compact */}
      <div className="relative">
        <textarea
          ref={inputRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe an image to generate..."
          rows={2}
          className="w-full resize-none rounded-xl border border-black/[.08] bg-white/60 px-3 py-2.5 text-sm leading-5 outline-none backdrop-blur-sm placeholder:text-[#a8a29e] focus:border-[#b8a08a]/40 focus:ring-2 focus:ring-[#b8a08a]/20"
          disabled={loading}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200/60 bg-red-50/80 px-3 py-2 text-xs text-red-700 backdrop-blur">
          {error}
        </div>
      )}

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={!prompt.trim() || loading}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#282521] px-4 py-2.5 text-sm font-medium text-white shadow-md transition hover:-translate-y-0.5 hover:bg-black disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {loading ? (
          <><Loader2 size={14} className="animate-spin" /> Generating...</>
        ) : (
          <><Sparkles size={14} /> Generate</>
        )}
      </button>

      {/* Generated image preview */}
      {generatedImage && (
        <div className="space-y-2">
          <div
            className="group relative cursor-zoom-in overflow-hidden rounded-xl border border-black/[.08] bg-white/60"
            onClick={() => setLightboxImage(generatedImage.url)}
          >
            <img src={generatedImage.url} alt={prompt} className="w-full object-contain" style={{ maxHeight: 320 }} />
            <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition group-hover:bg-black/10">
              <ZoomIn size={20} className="text-white opacity-0 drop-shadow transition group-hover:opacity-80" />
            </div>
          </div>
          <div className="flex gap-1.5">
            <button
              onClick={() => handleDownload(generatedImage)}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-black/[.06] bg-white/60 px-2 py-1.5 text-[11px] font-medium text-[#655f59] backdrop-blur transition hover:bg-white/80"
            >
              <Download size={12} /> Download
            </button>
            <button
              onClick={() => { setGeneratedImage(null); handleGenerate(); }}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-black/[.06] bg-white/60 px-2 py-1.5 text-[11px] font-medium text-[#655f59] backdrop-blur transition hover:bg-white/80"
            >
              <RefreshCw size={12} /> Regenerate
            </button>
          </div>
        </div>
      )}

      {/* History thumbnails */}
      {history.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {history.slice(1, 5).map((img, idx) => (
            <button
              key={idx}
              onClick={() => setGeneratedImage(img)}
              className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg border border-black/[.06] transition hover:border-[#b8a08a]/40"
            >
              <img src={img.url} alt={`Generated ${idx + 1}`} className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}

      {/* Lightbox with zoom */}
      {lightboxImage && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setLightboxImage(null)}
          onWheel={handleWheel}
        >
          <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.min(5, z + 0.3)); }}
              className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-white backdrop-blur transition hover:bg-white/30"
            >
              +
            </button>
            <span className="min-w-[40px] text-center text-xs text-white/70">{Math.round(zoom * 100)}%</span>
            <button
              onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.max(0.5, z - 0.3)); }}
              className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-white backdrop-blur transition hover:bg-white/30"
            >
              -
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleDownload({ url: lightboxImage, mime: "image/png" }); }}
              className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-white backdrop-blur transition hover:bg-white/30"
            >
              <Download size={14} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setLightboxImage(null); }}
              className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-white backdrop-blur transition hover:bg-white/30"
            >
              <X size={14} />
            </button>
          </div>
          <div
            className="flex items-center justify-center"
            style={{ cursor: zoom > 1 ? "grab" : "zoom-in" }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <img
              src={lightboxImage}
              alt="Generated"
              className="max-h-[85vh] max-w-[90vw] select-none rounded-lg object-contain shadow-2xl transition-transform"
              style={{ transform: `scale(${zoom}) translate(${pos.x / zoom}px, ${pos.y / zoom}px)` }}
              draggable={false}
            />
          </div>
          <p className="absolute bottom-4 text-xs text-white/50">Scroll to zoom &middot; Drag to pan &middot; Click outside to close</p>
        </div>
      )}
    </div>
  );
}
