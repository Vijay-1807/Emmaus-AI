"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import { apiFetch } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function DashboardPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  useEffect(() => {
    apiFetch<Workspace[]>("/api/workspaces")
      .then(setWorkspaces)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function createWorkspace() {
    if (!newName.trim()) return;
    try {
      const ws = await apiFetch<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: newName, description: newDesc }),
      });
      setWorkspaces((prev) => [ws, ...prev]);
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
    } catch {}
  }

  return (
    <AppLayout>
      <div className="p-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Workspaces</h1>
            <p className="text-text-muted text-sm mt-1">Manage your analysis workspaces</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-hover transition-colors"
          >
            New workspace
          </button>
        </div>

        {showCreate && (
          <div className="mb-6 bg-surface border border-border rounded-xl p-5">
            <h3 className="font-medium mb-3">Create workspace</h3>
            <input
              placeholder="Workspace name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full px-3 py-2 bg-bg border border-border rounded-lg text-text text-sm mb-3 focus:outline-none focus:border-primary"
            />
            <input
              placeholder="Description (optional)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="w-full px-3 py-2 bg-bg border border-border rounded-lg text-text text-sm mb-3 focus:outline-none focus:border-primary"
            />
            <div className="flex gap-2">
              <button onClick={createWorkspace} className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-hover">Create</button>
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 text-text-muted text-sm rounded-lg hover:text-text">Cancel</button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-text-muted text-sm">Loading...</div>
        ) : workspaces.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <p className="text-lg mb-2">No workspaces yet</p>
            <p className="text-sm">Create a workspace to start investigating.</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {workspaces.map((ws) => (
              <Link
                key={ws.id}
                href={`/workspace/${ws.id}`}
                className="block bg-surface border border-border rounded-xl p-5 hover:border-border-active transition-colors"
              >
                <h3 className="font-medium mb-1">{ws.name}</h3>
                {ws.description && (
                  <p className="text-text-muted text-sm mb-3 line-clamp-2">{ws.description}</p>
                )}
                <p className="text-xs text-text-muted">{formatDate(ws.created_at)}</p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
