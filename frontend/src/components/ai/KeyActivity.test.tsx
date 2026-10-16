import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { KeyActivity } from "./KeyActivity";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("KeyActivity", () => {
  it("lists the user's own key events with provider and result", async () => {
    const { calls } = installFetch((c) => {
      if (c.url.startsWith(`${API}/me/ai-providers-events`))
        return jsonResponse({
          items: [
            {
              id: "e1",
              household_id: null,
              actor_id: "u1",
              action: "ai_credential.tested",
              entity_type: "ai_credential",
              entity_id: "c1",
              details: { provider: "openai", result: "quota_exceeded" },
              created_at: "2026-10-16T00:00:00Z",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        });
      return jsonResponse({}, 404);
    });
    render(<KeyActivity />);
    expect(await screen.findByText("openai")).toBeInTheDocument();
    expect(screen.getByText(/quota exceeded/i)).toBeInTheDocument();
    expect(screen.getByText(/key tested/i)).toBeInTheDocument();
    expect(calls[0].url).toContain("limit=20");
  });
});
