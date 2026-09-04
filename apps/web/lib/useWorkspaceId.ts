"use client";

import { useEffect, useState } from "react";
import { resolveWorkspaceId } from "@/lib/workspace";

/**
 * Workspace id validated against the server. Handles the stale-id problem:
 * if localStorage references a deleted workspace, it is replaced with a live
 * one (or empty when none exist) instead of causing 404 spam.
 */
export function useWorkspaceId() {
  const [wsId, setWsId] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const id = await resolveWorkspaceId();
      if (!cancelled) {
        setWsId(id ?? "");
        setLoading(false);
      }
    })();
    const onChanged = async () => {
      const id = await resolveWorkspaceId();
      if (!cancelled) setWsId(id ?? "");
    };
    window.addEventListener("vedax:workspaces-changed", onChanged);
    return () => {
      cancelled = true;
      window.removeEventListener("vedax:workspaces-changed", onChanged);
    };
  }, []);

  return { wsId, loading, setWsId };
}
