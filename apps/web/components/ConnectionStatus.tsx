"use client";

import { useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

type ConnState = "online" | "connecting" | "offline";

const META: Record<ConnState, { dot: string; label: string; pulse: boolean }> = {
  online: { dot: "bg-emerald-500", label: "Online", pulse: false },
  connecting: { dot: "bg-amber-500", label: "Connecting", pulse: true },
  offline: { dot: "bg-red-500", label: "Offline", pulse: false },
};

/** Live backend status pill (replaces the static provider label).
 * Polls public /api/health: green = reachable, amber = checking,
 * red = unreachable (cold start, offline, or blocked). Dot-only on mobile.
 * Links to Settings where live provider routing is shown. */
export default function ConnectionStatus() {
  const [state, setState] = useState<ConnState>("connecting");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function ping() {
      if (cancelled) return;
      const ctrl = new AbortController();
      const killer = setTimeout(() => ctrl.abort(), 8000);
      try {
        const res = await fetch(`${getApiBase()}/api/health`, {
          signal: ctrl.signal,
          cache: "no-store",
        });
        if (!cancelled) setState(res.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setState("offline");
      } finally {
        clearTimeout(killer);
        if (!cancelled) timer = setTimeout(ping, 30000);
      }
    }

    void ping();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const meta = META[state];
  return (
    <a
      href="/settings"
      title="Backend connection - live provider routing in Settings"
      aria-live="polite"
      className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 transition hover:bg-black/[.06]"
    >
      <span className="relative flex h-2 w-2" aria-hidden="true">
        {meta.pulse && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${meta.dot}`} />
      </span>
      <span className="hidden text-[11px] text-[#5f5953] sm:inline">{meta.label}</span>
      <span className="sr-only">Backend {meta.label}</span>
    </a>
  );
}
