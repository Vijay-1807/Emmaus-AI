/**
 * Same-origin in local dev (Next rewrites proxy /api + /media, so no CORS
 * can ever break regardless of hostname: localhost, 127.0.0.1, LAN IP).
 * Absolute backend URL only when deployed elsewhere (Vercel -> Render).
 */
function getApiBase(): string {
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1" || host.startsWith("192.168.") || host.startsWith("10.")) {
      return "";
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || "";
}

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

export function setRefreshToken(token: string) {
  localStorage.setItem("vedax_refresh_token", token);
}

export function clearToken() {
  localStorage.removeItem("vedax_token");
  localStorage.removeItem("vedax_refresh_token");
}

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

export function storeSession(data: TokenResponse) {
  setToken(data.access_token);
  setRefreshToken(data.refresh_token);
}

let refreshPromise: Promise<string | null> | null = null;

async function performRefresh(): Promise<string | null> {
  const refreshToken = localStorage.getItem("vedax_refresh_token");
  if (!refreshToken) {
    clearToken();
    return null;
  }
  const response = await fetch(`${getApiBase()}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  }).catch(() => null);
  if (!response) return null;
  if (!response.ok) {
    clearToken();
    return null;
  }
  const data = (await response.json()) as TokenResponse;
  storeSession(data);
  return data.access_token;
}

async function refreshSession(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (item && typeof item === "object" && "msg" in item) return String(item.msg);
      return String(item);
    }).join("; ");
  }
  return fallback;
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await apiRequest(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, errorMessage(body.detail, res.statusText || "Request failed"));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function apiRequest(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData || options.body == null ? {} : { "Content-Type": "application/json" }),
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  let res = await fetch(`${getApiBase()}${path}`, { ...options, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    const refreshed = await refreshSession();
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed}`;
      res = await fetch(`${getApiBase()}${path}`, { ...options, headers });
    }
  }
  return res;
}

export function sseUrl(path: string): string {
  return `${getApiBase()}${path}`;
}

export async function ensureAnonymousSession(): Promise<string> {
  const existing = getToken();
  if (existing) {
    const check = await fetch(`${getApiBase()}/api/auth/me`, {
      headers: { Authorization: `Bearer ${existing}` },
    }).catch(() => null);
    if (check?.ok) return existing;
    if (check?.status === 401) {
      const refreshed = await refreshSession();
      if (refreshed) return refreshed;
    } else if (check === null) {
      return existing;
    }
  }
  try {
    const res = await fetch(`${getApiBase()}/api/auth/anonymous`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (res.ok) {
      const data = (await res.json()) as TokenResponse;
      storeSession(data);
      return data.access_token;
    }
  } catch (e) {
    console.error("anonymous session failed:", e);
  }
  throw new Error("Failed to create anonymous session");
}
