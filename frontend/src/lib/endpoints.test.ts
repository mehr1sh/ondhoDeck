import { beforeEach, describe, expect, it, vi } from "vitest";
import { installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { endpoints } from "./endpoints";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("listConstraints", () => {
  it("accepts the plain array the API returns (regression: Contract Explorer crashed)", async () => {
    installFetch(() => jsonResponse([{ id: "c1" }, { id: "c2" }]));
    const page = await endpoints.listConstraints("h1");
    expect(page.items.map((c) => c.id)).toEqual(["c1", "c2"]);
    expect(page.total).toBe(2);
  });

  it("still accepts a paginated response", async () => {
    installFetch(() => jsonResponse({ items: [{ id: "c1" }], total: 7, limit: 1, offset: 0 }));
    const page = await endpoints.listConstraints("h1");
    expect(page.total).toBe(7);
  });
});
