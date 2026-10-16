import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { StressView } from "./StressView";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const notFound = {
  id: "st1",
  scenario_id: "s1",
  engine_version: "1.1.0",
  search: { max_drawdown: 0.25, step: 0.0025, tolerance: 0.0001, grid: [] },
  found: false,
  boundary_drawdown: null,
  last_safe_drawdown: "0.25",
  first_shortfall_month: null,
  shortfall_amount: "0",
  grid_monotone: true,
  method: "Grid search over equity drawdown 0-25% in 0.25% steps, then bisection to 0.01% between the last passing and first failing grid points.",
  binding_constraints: [],
  attribution: [],
  key_events: [],
  created_at: "2026-03-01T10:00:00Z",
};

function setup() {
  const { calls } = installFetch((c) => {
    if (c.url.startsWith(`${API}/households/h1/stress-results`)) return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    if (c.method === "POST" && c.url === `${API}/scenarios/s1/stress`) return jsonResponse(notFound);
    return undefined;
  });
  render(<StressView householdId="h1" scenarioId="s1" currency="USD" canEdit />);
  return { calls, posts: () => calls.filter((c) => c.method === "POST") };
}

describe("StressView", () => {
  it("states each parameter's range and default in percent", async () => {
    setup();
    expect(await screen.findByText(/Enter a percentage between 0.25% and 10%; leave blank for 1%/)).toBeInTheDocument();
    expect(screen.getByText(/Enter a percentage between 0.01% and 1%; leave blank for 0.05%/)).toBeInTheDocument();
    expect(screen.getByText(/Enter a percentage above 0% and up to 95%; leave blank for 60%/)).toBeInTheDocument();
  });

  it("rejects out-of-range percentages in percent units without calling the API", async () => {
    const user = userEvent.setup();
    const { posts } = setup();
    await user.type(screen.getByLabelText(/Grid step/), "0.0025");
    await user.type(screen.getByLabelText(/Bisection tolerance/), "0.0001");
    await user.click(screen.getByRole("button", { name: /Run reverse stress/ }));
    expect(await screen.findByText("Enter a percentage between 0.25% and 10%, e.g. 1 for 1%.")).toBeInTheDocument();
    expect(screen.getByText("Enter a percentage between 0.01% and 1%, e.g. 0.05 for 0.05%.")).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });

  it("accepts the smallest allowed step and tolerance and sends them as fractions", async () => {
    const user = userEvent.setup();
    const { posts } = setup();
    await user.type(screen.getByLabelText(/Maximum drawdown/), "25");
    await user.type(screen.getByLabelText(/Grid step/), "0.25");
    await user.type(screen.getByLabelText(/Bisection tolerance/), "0.01");
    await user.click(screen.getByRole("button", { name: /Run reverse stress/ }));
    expect(await screen.findByText(/in 0.25% steps/)).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(posts()[0].body).toEqual({ max_drawdown: 0.25, step: 0.0025, tolerance: 0.0001 });
  });
});
