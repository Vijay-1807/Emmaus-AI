"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { Workspace } from "@/lib/types";

export default function WorkspaceRootPage() {
  const router = useRouter();

  useEffect(() => {
    apiFetch<Workspace[]>("/api/workspaces")
      .then((ws) => {
        if (ws.length > 0) {
          localStorage.setItem("vedax_workspace_id", ws[0].id);
          router.replace(`/workspace/${ws[0].id}`);
        } else {
          router.replace("/dashboard");
        }
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-text-muted text-sm">Loading workspace...</div>
    </div>
  );
}
