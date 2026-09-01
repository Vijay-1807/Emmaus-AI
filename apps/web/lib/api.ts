const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("vedax_token");
}

export function setToken(token: string) {
  localStorage.setItem("vedax_token", token);
}

export function clearToken() {
  localStorage.removeItem("vedax_token");
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function sseUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export async function ensureAnonymousSession(): Promise<string> {
  const existing = getToken();
  if (existing) return existing;
  try {
    const res = await fetch(`${API_BASE}/api/auth/anonymous`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (res.ok) {
      const data = await res.json();
      setToken(data.access_token);
      return data.access_token;
    }
  } catch {}
  return "";
}
