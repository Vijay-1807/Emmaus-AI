"use client";

import { useEffect, useState } from "react";

const delays = Array.from({ length: 9 }, (_, index) => {
  const row = Math.floor(index / 3);
  const column = index % 3;
  return (column + Math.abs(row - 1)) * 90;
});

export default function LoadingState({ label = "Thinking" }: { label?: string }) {
  const [deciseconds, setDeciseconds] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setDeciseconds((value) => value + 1), 100);
    return () => window.clearInterval(timer);
  }, []);

  const seconds = deciseconds / 10;
  const elapsed = seconds < 60
    ? `${seconds.toFixed(1)}s`
    : `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(1)}s`;

  return (
    <div className="flex items-center gap-2.5 py-0.5" role="status" aria-label={label}>
      <span aria-hidden className="grid grid-cols-[repeat(3,4px)] gap-[1.5px]">
        {delays.map((delay, index) => (
          <span
            key={index}
            className="size-[4px] rounded-[1px] bg-current motion-reduce:animate-none"
            style={{ animation: `pixel-on 650ms ease-in-out ${delay}ms infinite` }}
          />
        ))}
      </span>
      <span className="loading-shimmer text-[13px] font-medium">{label}</span>
      <span className="font-mono text-[11px] text-[#8d8780] tabular-nums">{elapsed}</span>
    </div>
  );
}
