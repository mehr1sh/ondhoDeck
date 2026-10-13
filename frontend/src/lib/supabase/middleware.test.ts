// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getUser } = vi.hoisted(() => ({ getUser: vi.fn() }));
vi.mock("@supabase/ssr", () => ({
  createServerClient: () => ({ auth: { getUser } }),
}));

import { updateSession } from "./middleware";

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "test-anon-key";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
  getUser.mockReset();
});

describe("middleware updateSession", () => {
  it("redirects unauthenticated requests for protected routes to /login with next", async () => {
    getUser.mockResolvedValue({ data: { user: null } });
    const res = await updateSession(new NextRequest("http://localhost:3000/households/h1/profile?x=1"));
    expect(res.status).toBe(307);
    const loc = new URL(res.headers.get("location")!);
    expect(loc.pathname).toBe("/login");
    expect(loc.searchParams.get("next")).toBe("/households/h1/profile?x=1");
  });

  it("lets authenticated requests through", async () => {
    getUser.mockResolvedValue({ data: { user: { id: "u1" } } });
    const res = await updateSession(new NextRequest("http://localhost:3000/settings"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("sends signed-in users away from the login page", async () => {
    getUser.mockResolvedValue({ data: { user: { id: "u1" } } });
    const res = await updateSession(new NextRequest("http://localhost:3000/login?next=/settings"));
    expect(new URL(res.headers.get("location")!).pathname).toBe("/settings");
  });

  it("passes through when configuration is missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    const res = await updateSession(new NextRequest("http://localhost:3000/households"));
    expect(res.headers.get("location")).toBeNull();
    expect(getUser).not.toHaveBeenCalled();
  });
});
