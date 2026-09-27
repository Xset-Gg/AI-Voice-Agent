export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "va_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — session-only auth */
  }
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

type Options = { method?: string; body?: unknown; form?: FormData; query?: Record<string, string | number | boolean | undefined | null> };

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const url = new URL(`${API_URL}/api${path}`);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server. Check that the API is running.");
  }
  if (res.status === 401 && token) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    let message: string = err?.message ?? `Request failed (${res.status})`;
    if (err?.code === "validation_error" && Array.isArray(err.details) && err.details.length) {
      message = err.details.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    }
    throw new ApiError(res.status, err?.code ?? "error", message, err?.details);
  }
  return data as T;
}

export function liveSocketUrl(): string | null {
  const token = getToken();
  if (!token) return null;
  return `${API_URL.replace(/^http/, "ws")}/api/calls/live?token=${encodeURIComponent(token)}`;
}
