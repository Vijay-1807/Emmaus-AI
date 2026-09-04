"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Mic, Upload, X, RotateCcw, Check, Volume2 } from "lucide-react";
import { formatBytes } from "@/lib/utils";
import { AIVoiceInput } from "@/components/ui/ai-voice-input";

interface VoiceRecordModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAudioReady: (file: File) => void;
}

export default function VoiceRecordModal({ isOpen, onClose, onAudioReady }: VoiceRecordModalProps) {
  const [mode, setMode] = useState<"record" | "upload">("record");
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Clear state when modal opens/closes
  useEffect(() => {
    if (!isOpen) {
      stopRecordingCleanup();
      resetState();
    }
  // resetState is a stable local reset helper; this effect only responds to modal visibility.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Escape + backdrop tap dismiss (mobile users expect both).
  // Never yank the sheet mid-recording — stop first, then close.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        stopRecordingCleanup();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  function handleBackdrop(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget && !isRecording) onClose();
  }

  function resetState() {
    setAudioBlob(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setRecordingTime(0);
    setIsRecording(false);
    setSelectedFile(null);
    setErrorMessage("");
  }

  function stopRecordingCleanup() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }

  const startRecording = useCallback(async () => {
    setErrorMessage("");
    resetState();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : "audio/webm";

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        setAudioBlob(blob);
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);
      };

      mediaRecorder.start(250);
      setIsRecording(true);

      timerRef.current = setInterval(() => {
        setRecordingTime((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "Microphone access denied or not available."
      );
    }
  // resetState is intentionally reset before every new recording.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setIsRecording(false);
  }, []);

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
  }

  function handleApply() {
    if (mode === "record" && audioBlob) {
      const ext = audioBlob.type.includes("mp4") ? "m4a" : "webm";
      const file = new File([audioBlob], `voice-recording-${Date.now()}.${ext}`, {
        type: audioBlob.type,
      });
      onAudioReady(file);
      onClose();
    } else if (mode === "upload" && selectedFile) {
      onAudioReady(selectedFile);
      onClose();
    }
  }

  function formatTimer(seconds: number) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in"
      onClick={handleBackdrop}
    >
      <div className="w-full max-w-md rounded-3xl border border-white/40 bg-[#fffdfa] p-6 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-black/[.06]">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
              <Mic size={18} />
            </div>
            <div>
              <h3 className="text-base font-bold text-[#1c1917]">Voice Input</h3>
              <p className="text-xs text-[#78716c]">Transcribe speech via Deepgram / Sarvam / Whisper STT</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-gray-400 transition hover:bg-black/[.05] hover:text-black"
          >
            <X size={16} />
          </button>
        </div>

        {/* Mode switcher tabs */}
        <div className="mt-4 flex rounded-xl bg-black/[.04] p-1">
          <button
            type="button"
            onClick={() => { setMode("record"); resetState(); }}
            className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition ${
              mode === "record"
                ? "bg-white text-[#1c1917] shadow-sm"
                : "text-gray-500 hover:text-black"
            }`}
          >
            Live Microphone
          </button>
          <button
            type="button"
            onClick={() => { setMode("upload"); resetState(); }}
            className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition ${
              mode === "upload"
                ? "bg-white text-[#1c1917] shadow-sm"
                : "text-gray-500 hover:text-black"
            }`}
          >
            Upload Audio File
          </button>
        </div>

        {/* Live Recording Body */}
        {mode === "record" && (
          <div className="my-4 flex flex-col items-center justify-center">
            {/* Premium AIVoiceInput with soundbar visualizer */}
            <AIVoiceInput
              isRecording={isRecording}
              onToggle={isRecording ? stopRecording : startRecording}
              visualizerBars={40}
            />

            {/* Status message */}
            <p className="mt-1 text-xs text-[#78716c] text-center">
              {isRecording
                ? "Recording... Speak clearly into your mic"
                : audioBlob
                ? "✓ Recording ready — click Analyze to transcribe"
                : "Click the mic above to start recording"}
            </p>

            {/* Audio playback preview */}
            {audioUrl && !isRecording && (
              <div className="mt-5 w-full rounded-2xl border border-black/[.06] bg-black/[.02] p-3">
                <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                  <span>Playback Preview</span>
                  <span>{formatTimer(recordingTime)}</span>
                </div>
                <audio
                  ref={audioPlayerRef}
                  src={audioUrl}
                  controls
                  className="w-full h-8"
                />
                <div className="mt-2 flex justify-end">
                  <button
                    type="button"
                    onClick={startRecording}
                    className="flex items-center gap-1 text-[11px] font-medium text-gray-500 hover:text-black transition"
                  >
                    <RotateCcw size={11} />
                    <span>Record again</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Upload Audio File Body */}
        {mode === "upload" && (
          <div className="my-6">
            <label className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-black/[.12] bg-black/[.01] p-8 text-center transition hover:border-black/[.25] hover:bg-black/[.03] cursor-pointer">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600 mb-3">
                <Upload size={22} />
              </div>
              <span className="text-sm font-semibold text-gray-800">
                {selectedFile ? selectedFile.name : "Select an audio file"}
              </span>
              <span className="mt-1 text-xs text-gray-500">
                {selectedFile
                  ? `${formatBytes(selectedFile.size)} · ready to attach`
                  : "Supports MP3, WAV, M4A, WEBM, OGG (up to 25MB)"}
              </span>
              <input
                type="file"
                className="hidden"
                accept=".mp3,.wav,.m4a,.webm,.ogg,audio/*"
                onChange={handleFileSelect}
              />
            </label>

            {audioUrl && selectedFile && (
              <div className="mt-4 rounded-2xl border border-black/[.06] bg-black/[.02] p-3">
                <div className="flex items-center gap-2 text-xs font-medium text-gray-700 mb-2">
                  <Volume2 size={14} className="text-indigo-600" />
                  <span className="truncate">{selectedFile.name}</span>
                </div>
                <audio src={audioUrl} controls className="w-full h-8" />
              </div>
            )}
          </div>
        )}

        {errorMessage && (
          <p className="mb-4 rounded-xl bg-red-50 p-2.5 text-center text-xs font-medium text-red-600">
            {errorMessage}
          </p>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-2 pt-4 border-t border-black/[.06]">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-xs font-semibold text-gray-500 transition hover:bg-black/[.05] hover:text-black"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={mode === "record" ? !audioBlob || isRecording : !selectedFile}
            className="flex items-center gap-1.5 rounded-xl bg-black px-5 py-2 text-xs font-semibold text-white shadow transition hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Check size={14} />
            <span>Use Audio</span>
          </button>
        </div>
      </div>
    </div>
  );
}
