/**
 * Central API client for the OndhoDeck API.
 *
 * - Attaches `Authorization: Bearer <access token>` from the Supabase session.
 * - Parses the error envelope `{"error": {code, message, request_id, details?}}` into ApiError.
 * - On 401 signs the user out and redirects to /login?next=<current path>&reason=expired.
 */
import { getPublicEnv } from "@/lib/env";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { loginUrlFor } from "@/lib/authGuard";

export const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;
  readonly retryAfter: number | null;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    details?: unknown;
    retryAfter?: number | null;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.requestId = opts.requestId ?? null;
    this.details = opts.details;
    this.retryAfter = opts.retryAfter ?? null;
  }

  get isUnauthorized() {
    return this.status === 401;
  }
  get isForbidden() {
    return this.status === 403;
  }
  get isNotFound() {
    return this.status === 404;
  }
  get isConflict() {
    return this.status === 409;
  }
  get isValidation() {
    return this.status === 422;
  }

  /** Field-level messages for 422 responses, keyed by dotted path without the leading "body". */
  get fieldErrors(): Record<string, string> {
    return extractFieldErrors(this.details);
  }
}

/**
 * Accepts FastAPI-style details (`[{loc: ["body","amount"], msg}]`), a `{field: message}` map,
 * or `{errors: [...]}`. Unknown shapes yield an empty map.
 */
export function extractFieldErrors(details: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const list = Array.isArray(details)
    ? details
    : details && typeof details === "object" && Array.isArray((details as { errors?: unknown }).errors)
      ? ((details as { errors: unknown[] }).errors)
      : null;
  if (list) {
    for (const item of list) {
      if (!item || typeof item !== "object") continue;
      const loc = (item as { loc?: unknown }).loc;
      const msg = (item as { msg?: unknown; message?: unknown }).msg ?? (item as { message?: unknown }).message;
      if (!Array.isArray(loc) || typeof msg !== "string") continue;
      const path = loc
        .filter((p, i) => !(i === 0 && (p === "body" || p === "query" || p === "path")))
        .map(String)
        .join(".");
      const key = path || "_";
      if (!(key in out)) out[key] = msg.replace(/^Value error, /, "");
    }
    return out;
  }
  if (details && typeof details === "object") {
    for (const [k, v] of Object.entries(details as Record<string, unknown>)) {
      if (typeof v === "string") out[k] = v;
      else if (Array.isArray(v) && typeof v[0] === "string") out[k] = v[0];
    }
  }
  return out;
}

/** Turns a relative URL returned by the API (e.g. "/api/v1/documents/x/content") into an absolute one. */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const base = getPublicEnv().apiBaseUrl;
  if (url.startsWith("/")) return `${base}${url}`;
  return `${base}${API_PREFIX}/${url}`;
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON-serialised unless `rawBody` is provided. */
  body?: unknown;
  /** Sent as-is (e.g. a File for PDF uploads). */
  rawBody?: BodyInit;
  contentType?: string;
  query?: Record<string, QueryValue>;
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Treat `path` as a full or API-relative URL (see resolveApiUrl) instead of prefixing /api/v1. */
  absoluteUrl?: boolean;
  /** Skip the global 401 handler (used by tests or flows that handle it themselves). */
  skipAuthRedirect?: boolean;
}

export function buildUrl(path: string, query?: Record<string, QueryValue>, absolute = false): string {
  const base = absolute ? resolveApiUrl(path) : `${getPublicEnv().apiBaseUrl}${API_PREFIX}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  if (!qs) return base;
  return `${base}${base.includes("?") ? "&" : "?"}${qs}`;
}

async function getAccessToken(): Promise<string | null> {
  try {
    const { data } = await getSupabaseBrowserClient().auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

let redirecting = false;

/** Indirection so navigation can be observed in tests. */
export const browserNavigation = {
  assign(url: string) {
    window.location.assign(url);
  },
};

/** Signs out and sends the browser to the login page, remembering where the user was. */
export async function handleSessionExpired(): Promise<void> {
  if (redirecting) return;
  redirecting = true;
  try {
    await getSupabaseBrowserClient().auth.signOut({ scope: "local" });
  } catch {
    // ignore: we redirect regardless
  }
  if (typeof window !== "undefined") {
    const { pathname, search } = window.location;
    browserNavigation.assign(loginUrlFor(pathname, search, "expired"));
  }
  // Allow future redirects (e.g. in tests or after navigation is cancelled).
  setTimeout(() => {
    redirecting = false;
  }, 1000);
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  const retryAfterHeader = res.headers.get("Retry-After");
  const retryAfter = retryAfterHeader ? Number(retryAfterHeader) || null : null;
  const env = (body as { error?: Record<string, unknown> } | null)?.error;
  if (env && typeof env === "object") {
    return new ApiError({
      status: res.status,
      code: typeof env.code === "string" ? env.code : `http_${res.status}`,
      message: typeof env.message === "string" ? env.message : res.statusText || "Request failed",
      requestId:
        (typeof env.request_id === "string" ? env.request_id : null) ?? res.headers.get("X-Request-ID"),
      details: env.details,
      retryAfter,
    });
  }
  return new ApiError({
    status: res.status,
    code: `http_${res.status}`,
    message: res.statusText || `Request failed with status ${res.status}`,
    requestId: res.headers.get("X-Request-ID"),
    retryAfter,
  });
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.rawBody !== undefined ? "POST" : "GET");
  const url = buildUrl(path, opts.query, opts.absoluteUrl);
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = await getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let body: BodyInit | undefined;
  if (opts.rawBody !== undefined) {
    body = opts.rawBody;
    if (opts.contentType) headers["Content-Type"] = opts.contentType;
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(url, { method, headers, body, signal: opts.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Could not reach the OndhoDeck API. Check your connection and try again.",
    });
  }

  if (!res.ok) {
    const err = await parseError(res);
    if (err.status === 401 && !opts.skipAuthRedirect) {
      void handleSessionExpired();
    }
    throw err;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError({
      status: res.status,
      code: "invalid_response",
      message: "The API returned a response that could not be read.",
      requestId: res.headers.get("X-Request-ID"),
    });
  }
}

export const api = {
  get: <T>(path: string, query?: Record<string, QueryValue>, signal?: AbortSignal) =>
    apiRequest<T>(path, { method: "GET", query, signal }),
  post: <T>(path: string, body?: unknown, extra: Partial<RequestOptions> = {}) =>
    apiRequest<T>(path, { method: "POST", body: body ?? {}, ...extra }),
  patch: <T>(path: string, body: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body: unknown) => apiRequest<T>(path, { method: "PUT", body }),
  del: <T = void>(path: string, body?: unknown) => apiRequest<T>(path, { method: "DELETE", body }),
};

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Normalises a list response that may be a Page<T> or a bare array. */
export function itemsOf<T>(resp: { items: T[] } | T[] | null | undefined): T[] {
  if (!resp) return [];
  return Array.isArray(resp) ? resp : resp.items ?? [];
}
