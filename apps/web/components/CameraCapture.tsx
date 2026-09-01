"use client";

import { useRef, useState, useCallback } from "react";

interface CameraCaptureProps {
  onCapture: (blob: Blob, filename: string) => void;
  onClose: () => void;
}

export default function CameraCapture({ onCapture, onClose }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [streaming, setStreaming] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [captured, setCaptured] = useState<Blob | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setStreaming(true);
    } catch {
      alert("Camera access denied or unavailable");
    }
  }, []);

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
    }, "image/jpeg", 0.92);
  }, []);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setStreaming(false);
  }, []);

  const handleUpload = useCallback(() => {
    if (!captured) return;
    onCapture(captured, `capture-${Date.now()}.jpg`);
  }, [captured, onCapture]);

  const handleRetake = useCallback(() => {
    setCaptured(null);
    setPreview(null);
    startCamera();
  }, [startCamera]);

  const handleClose = useCallback(() => {
    stopStream();
    setCaptured(null);
    setPreview(null);
    onClose();
  }, [stopStream, onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
      <div className="bg-surface border border-border rounded-xl max-w-lg w-full overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h3 className="text-sm font-medium">Camera Capture</h3>
          <button onClick={handleClose} className="text-text-muted hover:text-text text-lg">&times;</button>
        </div>

        <div className="relative aspect-video bg-black">
          {preview ? (
            <img src={preview} alt="Captured" className="w-full h-full object-contain" />
          ) : (
            <>
              <video ref={videoRef} className="w-full h-full object-cover" autoPlay playsInline muted />
              {!streaming && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <button
                    onClick={startCamera}
                    className="px-6 py-3 bg-primary text-white rounded-lg text-sm hover:bg-primary-hover"
                  >
                    Open Camera
                  </button>
                </div>
              )}
            </>
          )}
          <canvas ref={canvasRef} className="hidden" />
        </div>

        <div className="flex gap-2 p-4">
          {streaming && !captured && (
            <button onClick={capture} className="flex-1 py-2.5 bg-primary text-white rounded-lg text-sm hover:bg-primary-hover">
              Capture
            </button>
          )}
          {captured && (
            <>
              <button onClick={handleRetake} className="flex-1 py-2.5 border border-border text-text rounded-lg text-sm hover:bg-surface-2">
                Retake
              </button>
              <button onClick={handleUpload} className="flex-1 py-2.5 bg-primary text-white rounded-lg text-sm hover:bg-primary-hover">
                Upload
              </button>
            </>
          )}
          {!streaming && !captured && (
            <button onClick={handleClose} className="flex-1 py-2.5 border border-border text-text-muted rounded-lg text-sm hover:bg-surface-2">
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
