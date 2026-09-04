"use client";

import { Mic } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface AIVoiceInputProps {
  onStart?: () => void;
  onStop?: (duration: number) => void;
  visualizerBars?: number;
  demoMode?: boolean;
  demoInterval?: number;
  className?: string;
  isRecording?: boolean;
  onToggle?: () => void;
}

export function AIVoiceInput({
  onStart,
  onStop,
  visualizerBars = 48,
  demoMode = false,
  demoInterval = 3000,
  className,
  isRecording: externalIsRecording,
  onToggle: externalOnToggle,
}: AIVoiceInputProps) {
  const [internalSubmitted, setInternalSubmitted] = useState(false);
  const [time, setTime] = useState(0);
  const timeRef = useRef(0);
  const [isClient, setIsClient] = useState(false);
  const [isDemo, setIsDemo] = useState(demoMode);

  const isControlled = externalIsRecording !== undefined;
  const isListening = isControlled ? externalIsRecording : internalSubmitted;

  useEffect(() => {
    setIsClient(true);
  }, []);

  useEffect(() => {
    let intervalId: NodeJS.Timeout;

    if (isListening) {
      onStart?.();
      intervalId = setInterval(() => {
        timeRef.current += 1;
        setTime(timeRef.current);
      }, 1000);
    } else {
      if (timeRef.current > 0) {
        onStop?.(timeRef.current);
      }
      timeRef.current = 0;
      setTime(0);
    }

    return () => clearInterval(intervalId);
  }, [isListening, onStart, onStop]);

  useEffect(() => {
    if (!isDemo) return;

    let timeoutId: NodeJS.Timeout;
    const runAnimation = () => {
      setInternalSubmitted(true);
      timeoutId = setTimeout(() => {
        setInternalSubmitted(false);
        timeoutId = setTimeout(runAnimation, 1000);
      }, demoInterval);
    };

    const initialTimeout = setTimeout(runAnimation, 100);
    return () => {
      clearTimeout(timeoutId);
      clearTimeout(initialTimeout);
    };
  }, [isDemo, demoInterval]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const handleClick = () => {
    if (isControlled && externalOnToggle) {
      externalOnToggle();
      return;
    }
    if (isDemo) {
      setIsDemo(false);
      setInternalSubmitted(false);
    } else {
      setInternalSubmitted((prev) => !prev);
    }
  };

  return (
    <div className={cn("w-full py-4", className)}>
      <div className="relative max-w-xl w-full mx-auto flex items-center flex-col gap-3">
        <button
          className={cn(
            "group w-16 h-16 rounded-2xl flex items-center justify-center transition-all shadow-sm border",
            isListening
              ? "bg-red-500/10 border-red-500/30 text-red-600 shadow-red-500/10 scale-105"
              : "bg-black/[.03] border-black/[.08] hover:bg-black/[.06] text-black/70"
          )}
          type="button"
          onClick={handleClick}
          title={isListening ? "Click to stop recording" : "Click to speak"}
        >
          {isListening ? (
            <div
              className="w-5 h-5 rounded-sm animate-spin bg-red-600 cursor-pointer pointer-events-auto"
              style={{ animationDuration: "3s" }}
            />
          ) : (
            <Mic className="w-6 h-6 text-black/70 transition group-hover:scale-110" />
          )}
        </button>

        <span
          className={cn(
            "font-mono text-sm font-semibold transition-opacity duration-300",
            isListening ? "text-black/80 font-bold" : "text-black/35"
          )}
        >
          {formatTime(time)}
        </span>

        {/* Visualizer Soundbars */}
        <div className="h-5 w-64 flex items-center justify-center gap-0.5 px-2">
          {[...Array(visualizerBars)].map((_, i) => (
            <div
              key={i}
              className={cn(
                "w-0.5 rounded-full transition-all duration-300",
                isListening
                  ? "bg-indigo-500 animate-pulse"
                  : "bg-black/10 h-1"
              )}
              style={
                isListening && isClient
                  ? {
                      height: `${15 + ((Math.sin(i * 0.4 + time * 2) + 1) / 2) * 75}%`,
                      animationDelay: `${i * 0.04}s`,
                    }
                  : undefined
              }
            />
          ))}
        </div>

        <p className="text-xs text-black/60 font-medium">
          {isListening ? "Listening... Click to stop & transcribe" : "Click the mic to speak"}
        </p>
      </div>
    </div>
  );
}
