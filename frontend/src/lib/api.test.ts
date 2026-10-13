import { beforeEach, describe, expect, it, vi } from "vitest";
import { errorResponse, installFetch, jsonResponse, makeAuthMock, API } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { ApiError, apiRequest, browserNavigation, extractFieldErrors, itemsOf, resolveApiUrl } from "./api";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("apiRequest", () => {
  it("attaches the bearer token and parses JSON", async () => {
    const { calls } = installFetch(() => jsonResponse({ id: "h1" }));
    const out = await apiRequest<{ id: string }>("/households/h1");
    expect(out).toEqual({ id: "h1" });
    expect(calls[0]!.url).toBe(`${API}/households/h1`);
    expect(calls[0]!.headers.Authorization).toBe("Bearer test-token");
  });

  it("serialises query params and skips empty ones", async () => {
    const { calls } = installFetch(() => jsonResponse({ items: [], total: 0, limit: 10, offset: 0 }));
    await apiRequest("/households/h1/constraints", { query: { limit: 10, document_id: undefined, review_status: "" } });
    expect(calls[0]!.url).toBe(`${API}/households/h1/constraints?limit=10`);
  });

  it("on 401 signs out and redirects to login with next and reason", async () => {
    window.history.replaceState({}, "", "/households/h1?x=1");
    const assign = vi.spyOn(browserNavigation, "assign").mockImplementation(() => {});
    installFetch(() => errorResponse(401, "token_expired", "Token expired", "req-401"));
    const err = (await apiRequest("/me").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("token_expired");
    await vi.waitFor(() => expect(assign).toHaveBeenCalled());
    expect(auth.signOut).toHaveBeenCalled();
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fhouseholds%2Fh1%3Fx%3D1&reason=expired");
  });

  it("parses 422 validation details into field errors", async () => {
    installFetch(() =>
      errorResponse(422, "validation_error", "Invalid input", "req-422", [
        { loc: ["body", "amount"], msg: "Input should be greater than or equal to 0", type: "greater_than_equal" },
        { loc: ["body", "assumptions", "equity_drawdown"], msg: "Value error, too large" },
      ]),
    );
    const err = (await apiRequest("/households/h1/assets", { method: "POST", body: {} }).catch((e) => e)) as ApiError;
    expect(err.isValidation).toBe(true);
    expect(err.fieldErrors).toEqual({
      amount: "Input should be greater than or equal to 0",
      "assumptions.equity_drawdown": "too large",
    });
  });

  it("keeps request_id on 500 errors", async () => {
    installFetch(() => errorResponse(500, "internal_error", "Unexpected error", "req-500"));
    const err = (await apiRequest("/me").catch((e) => e)) as ApiError;
    expect(err.status).toBe(500);
    expect(err.requestId).toBe("req-500");
    expect(err.message).toBe("Unexpected error");
  });

  it("handles non-envelope errors and network failures", async () => {
    installFetch(() => new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    const err = (await apiRequest("/me").catch((e) => e)) as ApiError;
    expect(err.status).toBe(502);
    expect(err.code).toBe("http_502");

    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const net = (await apiRequest("/me").catch((e) => e)) as ApiError;
    expect(net.code).toBe("network_error");
    expect(net.status).toBe(0);
  });

  it("returns undefined for 204", async () => {
    installFetch(() => jsonResponse(null, 204));
    await expect(apiRequest("/assets/a1", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

describe("helpers", () => {
  it("resolves relative API URLs", () => {
    expect(resolveApiUrl("/api/v1/documents/d1/content")).toBe("http://api.test/api/v1/documents/d1/content");
    expect(resolveApiUrl("https://cdn.example/x")).toBe("https://cdn.example/x");
  });
  it("extracts field errors from a map", () => {
    expect(extractFieldErrors({ name: "Required" })).toEqual({ name: "Required" });
    expect(extractFieldErrors("nope")).toEqual({});
  });
  it("normalises list responses", () => {
    expect(itemsOf([1, 2])).toEqual([1, 2]);
    expect(itemsOf({ items: [3] })).toEqual([3]);
    expect(itemsOf(undefined)).toEqual([]);
  });
});
