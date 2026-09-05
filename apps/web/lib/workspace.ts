import { ApiError, apiFetch, ensureAnonymousSession } from "@/lib/api";
import type { Dataset, Document, Workspace } from "@/lib/types";

const KEY = "vedax_workspace_id";

export function getStoredWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(KEY);
}

export function setStoredWorkspaceId(id: string) {
  localStorage.setItem(KEY, id);
}

/** Remove the stored id only if it matches (avoids clobbering a newer selection). */
export function clearStoredWorkspaceIdIf(id: string | null) {
  if (!id) return;
  if (localStorage.getItem(KEY) === id) {
    localStorage.removeItem(KEY);
  }
}

export function isNotFoundError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

/**
 * Guarantee a workspace id for an upload: reuse the current one, or create
 * "My Workspace" on the fly so the Upload button never dead-ends.
 * Returns null when creation fails.
 */
export async function ensureWorkspaceId(current: string | null): Promise<string | null> {
  if (current) return current;
  try {
    await ensureAnonymousSession();
    const ws = await apiFetch<Workspace>("/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name: "My Workspace" }),
    });
    localStorage.setItem(KEY, ws.id);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("vedax:workspaces-changed"));
    }
    return ws.id;
  } catch {
    return null;
  }
}

/**
 * Resolve a usable workspace id: the stored one if it still exists on the
 * server, otherwise the most recent workspace, otherwise null.
 * Never throws — returns null when offline or when no workspaces exist.
 */
export interface LibrarySource {
  id: string;
  filename: string;
  source_type: string;
  workspace_id: string;
}

export async function listLibrarySources(): Promise<LibrarySource[]> {
  try {
    await ensureAnonymousSession();
    const workspaces = await apiFetch<Workspace[]>("/api/workspaces");
    const sources: LibrarySource[] = [];
    for (const ws of workspaces) {
      const [docs, datasets] = await Promise.all([
        apiFetch<Document[]>(`/api/documents?workspace_id=${ws.id}`).catch(() => [] as Document[]),
        apiFetch<Dataset[]>(`/api/datasets?workspace_id=${ws.id}`).catch(() => [] as Dataset[]),
      ]);
      docs.forEach((d) =>
        sources.push({ id: d.id, filename: d.filename, source_type: d.source_type, workspace_id: ws.id })
      );
      datasets.forEach((d) =>
        sources.push({ id: d.id, filename: d.filename, source_type: "dataset", workspace_id: ws.id })
      );
    }
    return sources;
  } catch {
    return [];
  }
}

export async function copyDocumentToWorkspace(
  sourceWs: string,
  documentId: string,
  targetWs: string,
): Promise<string | null> {
  try {
    const data = await apiFetch<{ document_id: string }>("/api/documents/copy", {
      method: "POST",
      body: JSON.stringify({
        source_workspace_id: sourceWs,
        document_id: documentId,
        target_workspace_id: targetWs,
      }),
    });
    return data.document_id;
  } catch {
    return null;
  }
}

export async function copyDatasetToWorkspace(
  sourceWs: string,
  datasetId: string,
  targetWs: string,
): Promise<string | null> {
  try {
    const exists = await apiFetch<Dataset[]>(`/api/datasets?workspace_id=${targetWs}`).catch(() => [] as Dataset[]);
    if (exists.some((d) => d.id === datasetId)) return datasetId;
    // Re-upload is not possible without bytes; use documents/copy pattern:
    // datasets are indexed chunks too — reuse the same deep-copy idea via raw API
    const res = await apiFetch<{ dataset_id: string }>("/api/datasets/copy", {
      method: "POST",
      body: JSON.stringify({
        source_workspace_id: sourceWs,
        dataset_id: datasetId,
        target_workspace_id: targetWs,
      }),
    }).catch(() => null);
    return res?.dataset_id ?? null;
  } catch {
    return null;
  }
}

export async function resolveWorkspaceId(): Promise<string | null> {
  try {
    await ensureAnonymousSession();
    const list = await apiFetch<Workspace[]>("/api/workspaces");
    if (list.length === 0) {
      localStorage.removeItem(KEY);
      return null;
    }
    const stored = localStorage.getItem(KEY);
    if (stored && list.some((w) => w.id === stored)) return stored;
    localStorage.setItem(KEY, list[0].id);
    return list[0].id;
  } catch {
    return getStoredWorkspaceId();
  }
}
