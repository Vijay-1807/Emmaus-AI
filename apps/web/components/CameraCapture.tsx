"use client";

import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { Aperture, Camera, Loader2, X, RotateCcw, Check, SwitchCamera } from "lucide-react";

interface CameraCaptureProps {
  onCapture: (blob: Blob, filename: string) => void;
  onClose: () => void;
}

/** Phones/tablets: jump straight to the native camera app (front + rear). */
function isMobileDevice(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  return (
    /Android|iPhone|iPad|iPod|Mobile|Tablet/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 0 && window.matchMedia("(pointer: coarse)").matches)
  );
}

export default function CameraCapture({ onCapture, onClose }: CameraCaptureProps) {
  const mobile = useMemo(isMobileDevice, []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const runId = useRef(0);
  const envInputRef = useRef<HTMLInputElement>(null);
  const userInputRef = useRef<HTMLInputElement>(null);
  const [streaming, setStreaming] = useState(false);
  const [starting, setStarting] = useState(!mobile);
  const [preview, setPreview] = useState<string | null>(null);
  const [captured, setCaptured] = useState<Blob | null>(null);
  const [error, setError] = useState("");
  // Laptop = single webcam: no Flip button. (Kept for external/rare dual-cam setups.)
  const [multiCam, setMultiCam] = useState(false);
  const [facing, setFacing] = useState<"user" | "environment">("environment");

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setStreaming(false);
  }, []);

  const startCamera = useCallback(
    async (mode: "user" | "environment") => {
      if (mobile) return;
      const id = ++runId.current;
      const alive = () => id === runId.current;
      setError("");
      setStarting(true);
      stopStream();
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("This browser does not support camera access.");
        }
        // Hide Flip unless the machine really has front + rear cameras.
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const cams = devices.filter((d) => d.kind === "videoinput");
          setMultiCam(cams.length > 1);
        } catch {
          /* label/device lookup may need permission first — ignore */
        }
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: mode },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (!alive()) {
          // Superseded (StrictMode remount / Flip / retake) — release the tracks.
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          // play() races (StrictMode remount, track swaps) throw AbortErrors —
          // never surface those as camera failures.
          videoRef.current.play().catch(() => {});
        }
        setStreaming(true);
      } catch (err) {
        if (alive()) {
          setError(
            err instanceof Error && err.message
              ? err.message
              : "Camera unavailable. Check browser permissions."
          );
        }
      } finally {
        if (alive()) setStarting(false);
      }
    },
    [mobile, stopStream]
  );

  // Laptop: open the webcam immediately. Mobile: open the native camera app.
  useEffect(() => {
    if (mobile) {
      envInputRef.current?.click();
      return;
    }
    const mountedRun = runId.current;
    void startCamera("user");
    return () => {
      // The ref is the cancellation token for an in-flight camera request.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      if (runId.current === mountedRun) runId.current++;
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleNativeFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return; // user backed out of the camera app — choices stay open
    onCapture(file, file.name || `capture-${Date.now()}.jpg`);
  }

  const capture = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (blob) {
        setCaptured(blob);
        setPreview(URL.createObjectURL(blob));
        stopStream();
      }
    }, "image/jpeg", 0.85);
  }, [stopStream]);

  const handleRetake = useCallback(() => {
    setCaptured(null);
    if (preview) {
      URL.revokeObjectURL(preview);
      setPreview(null);
    }
    void startCamera(facing);
  }, [facing, preview, startCamera]);

  const handleUse = useCallback(() => {
    if (!captured) return;
    onCapture(captured, `capture-${Date.now()}.jpg`);
  }, [captured, onCapture]);

  const handleClose = useCallback(() => {
    stopStream();
    setCaptured(null);
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    onClose();
  }, [stopStream, preview, onClose]);

  // Escape + backdrop tap dismiss (mobile users expect both).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleClose]);

  function handleBackdrop(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) handleClose();
  }

  function switchFacing() {
    const next = facing === "user" ? "environment" : "user";
    setFacing(next);
    setCaptured(null);
    if (preview) {
      URL.revokeObjectURL(preview);
      setPreview(null);
    }
    void startCamera(next);
  }

  // ── Mobile: native camera app (front + rear live in the OS camera UI) ──
  if (mobile) {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        onClick={handleBackdrop}
      >
        <div className="w-full max-w-sm rounded-3xl border border-white/50 bg-[#fffdf8] p-6 shadow-2xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-black/[.05] text-[#514c47]">
                <Camera size={17} />
              </span>
              <div>
                <h3 className="text-sm font-bold">Take a photo</h3>
                <p className="text-[11px] text-[#8d8780]">Opens your camera app</p>
              </div>
            </div>
            <button
              onClick={handleClose}
              aria-label="Close camera"
              className="rounded-full p-1.5 text-[#8d8780] transition hover:bg-black/[.06] hover:text-black"
            >
              <X size={16} />
            </button>
          </div>
          <div className="mt-5 grid gap-2">
            <button
              onClick={() => envInputRef.current?.click()}
              className="flex items-center justify-center gap-2 rounded-2xl bg-[#282521] py-3 text-sm font-semibold text-white shadow-md transition hover:bg-black"
            >
              <Aperture size={15} />
              Rear camera
            </button>
            <button
              onClick={() => userInputRef.current?.click()}
              className="flex items-center justify-center gap-2 rounded-2xl border border-black/[.1] bg-white/70 py-3 text-sm font-semibold transition hover:bg-white"
            >
              <SwitchCamera size={15} />
              Front camera
            </button>
          </div>
          <input
            ref={envInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={handleNativeFile}
          />
          <input
            ref={userInputRef}
            type="file"
            accept="image/*"
            capture="user"
            className="hidden"
            onChange={handleNativeFile}
          />
        </div>
      </div>
    );
  }

  // ── Laptop: in-browser webcam (single camera → no Flip unless 2+ found) ──
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-3xl border border-white/50 bg-[#fffdf8] shadow-2xl">
        <div className="flex items-center justify-between border-b border-black/[.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-black/[.05] text-[#514c47]">
              <Camera size={16} />
            </span>
            <div>
              <h3 className="text-sm font-bold">Camera Capture</h3>
              <p className="text-[11px] text-[#8d8780]">Webcam</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {multiCam && streaming && !captured && (
              <button
                onClick={switchFacing}
                title="Switch camera"
                className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-[#655f59] transition hover:bg-black/[.06] hover:text-black"
              >
                <SwitchCamera size={14} />
                <span className="hidden sm:inline">Flip</span>
              </button>
            )}
            <button
              onClick={handleClose}
              aria-label="Close camera"
              className="rounded-full p-1.5 text-[#8d8780] transition hover:bg-black/[.06] hover:text-black"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="relative aspect-[4/3] bg-black sm:aspect-video">
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="Captured" className="h-full w-full object-contain" />
          ) : (
            <>
              <video ref={videoRef} className="h-full w-full object-cover" autoPlay playsInline muted />
              {(starting || error) && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/70 p-6 text-center">
                  {error ? (
                    <>
                      <p className="max-w-xs text-sm text-white/85">{error}</p>
                      <button
                        onClick={() => void startCamera(facing)}
                        className="rounded-full bg-white px-5 py-2 text-xs font-bold text-black transition hover:bg-white/90"
                      >
                        Try again
                      </button>
                    </>
                  ) : (
                    <>
                      <Loader2 size={28} className="animate-spin text-white/80" />
                      <p className="text-sm text-white/70">Starting camera…</p>
                    </>
                  )}
                </div>
              )}
            </>
          )}
          <canvas ref={canvasRef} className="hidden" />
        </div>

        <div className="flex gap-2 p-4">
          {streaming && !captured && (
            <button
              onClick={capture}
              className="grid h-12 w-12 mx-auto place-items-center rounded-full bg-[#282521] text-white shadow-lg transition hover:scale-105 hover:bg-black"
              aria-label="Take photo"
              title="Take photo"
            >
              <span className="h-8 w-8 rounded-full border-2 border-white/90" />
            </button>
          )}
          {captured && (
            <>
              <button
                onClick={handleRetake}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-full border border-black/[.1] bg-white/70 py-2.5 text-xs font-semibold transition hover:bg-white"
              >
                <RotateCcw size={13} />
                Retake
              </button>
              <button
                onClick={handleUse}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-[#282521] py-2.5 text-xs font-semibold text-white shadow-md transition hover:bg-black"
              >
                <Check size={14} />
                Use photo
              </button>
            </>
          )}
          {!streaming && !captured && !starting && (
            <button
              onClick={handleClose}
              className="flex-1 rounded-full border border-black/[.1] bg-white/70 py-2.5 text-xs font-semibold text-[#655f59] transition hover:bg-white hover:text-black"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
