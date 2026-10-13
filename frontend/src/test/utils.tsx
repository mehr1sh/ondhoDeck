import { vi } from "vitest";

export const API = "http://api.test/api/v1";

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  if (status === 204) return new Response(null, { status });
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function errorResponse(status: number, code: string, message: string, requestId = "req-123", details?: unknown) {
  return jsonResponse({ error: { code, message, request_id: requestId, ...(details !== undefined ? { details } : {}) } }, status);
}

export interface RecordedCall {
  url: string;
  method: string;
  body: unknown;
  headers: Record<string, string>;
}

type Handler = (call: RecordedCall) => Response | Promise<Response> | undefined;

/** Installs a fetch mock that routes by handler and records calls (JSON bodies parsed). */
export function installFetch(handler: Handler) {
  const calls: RecordedCall[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init.method ?? "GET").toUpperCase();
    let body: unknown = init.body;
    if (typeof init.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    const headers = { ...(init.headers as Record<string, string> | undefined) };
    const call = { url, method, body, headers };
    calls.push(call);
    const res = await handler(call);
    if (!res) throw new Error(`Unhandled fetch: ${method} ${url}`);
    return res;
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function makeAuthMock(overrides: Record<string, unknown> = {}) {
  return {
    getSession: vi.fn(async () => ({ data: { session: { access_token: "test-token", user: { id: "u1", email: "a@b.co" } } }, error: null })),
    signOut: vi.fn(async () => ({ error: null })),
    signInWithPassword: vi.fn(),
    signUp: vi.fn(),
    resetPasswordForEmail: vi.fn(),
    updateUser: vi.fn(),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
    ...overrides,
  };
}
