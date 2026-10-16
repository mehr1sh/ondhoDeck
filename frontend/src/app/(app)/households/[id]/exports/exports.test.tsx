import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";
import { HouseholdProvider } from "@/components/household/HouseholdContext";
import type { HouseholdOut } from "@/lib/types";

const { auth, nav } = vi.hoisted(() => ({ auth: {} as Record<string, unknown>, nav: { search: "" } }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(nav.search) }));

import ExportsPage from "./page";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
  nav.search = "";
});

const household: HouseholdOut = {
  id: "h1",
  name: "Rivera household",
  reporting_currency: "USD",
  start_calendar_month: 1,
  notes: null,
  is_demo: false,
  role: "advisor" as HouseholdOut["role"],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, limit: 20, offset: 0 });
const run = (id: string, created_at: string) => ({ id, scenario_id: "s1", scenario_name: "Rate shock", created_at });
const exp = (o: Record<string, unknown>) => ({
  id: "e1",
  household_id: "h1",
  run_id: "r1",
  blind_spot_report_id: null,
  kind: "report_pdf",
  status: "ready",
  filename: "rivera-report.pdf",
  size_bytes: 2048,
  error_message: null,
  created_at: "2026-03-01T10:00:00Z",
  completed_at: "2026-03-01T10:00:05Z",
  ...o,
});

function setup({ runs = [run("r1", "2026-03-02T10:00:00Z"), run("r2", "2026-03-01T10:00:00Z")], exports: initial = [] as unknown[] } = {}) {
  const list = [...initial];
  const { calls } = installFetch((c) => {
    if (c.url.startsWith(`${API}/households/h1/runs`)) return page(runs);
    if (c.url.startsWith(`${API}/households/h1/blind-spot-reports`)) return page([]);
    if (c.url.startsWith(`${API}/households/h1/scenarios`)) return page([{ id: "s1", name: "Rate shock" }]);
    if (c.url.startsWith(`${API}/households/h1/exports`) && c.method === "GET") return page(list);
    if (c.url === `${API}/households/h1/exports` && c.method === "POST") {
      const body = c.body as Record<string, unknown>;
      const created = exp({ id: `new-${list.length}`, status: "queued", filename: null, run_id: body.run_id ?? null, kind: body.kind });
      list.unshift(created);
      return jsonResponse(created, 202);
    }
    return undefined;
  });
  render(
    <HouseholdProvider household={household}>
      <ExportsPage />
    </HouseholdProvider>,
  );
  return { posts: () => calls.filter((c) => c.method === "POST") };
}

describe("household Reports tab", () => {
  it("creates a liquidity report for the analysis named in the link and lists it", async () => {
    nav.search = "run_id=r2";
    const user = userEvent.setup();
    const { posts } = setup();
    expect(await screen.findByLabelText("Analysis")).toHaveValue("r2");
    await user.click(screen.getByRole("button", { name: "Liquidity report (PDF)" }));
    expect(posts()[0].body).toEqual({ kind: "report_pdf", run_id: "r2" });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Liquidity report (PDF)")).toBeInTheDocument();
    expect(within(table).getByText("Preparing…")).toBeInTheDocument();
  });

  it("defaults to the latest analysis and exports terms without a run", async () => {
    const user = userEvent.setup();
    const { posts } = setup();
    expect(await screen.findByLabelText("Analysis")).toHaveValue("r1");
    await user.click(screen.getByRole("button", { name: "Terms (CSV)" }));
    expect(posts()[0].body).toEqual({ kind: "constraints_csv" });
  });

  it("shows ready downloads and failure reasons, and explains what to do without analyses", async () => {
    setup({
      runs: [],
      exports: [exp({}), exp({ id: "e2", kind: "simulation_csv", status: "failed", error_message: "Renderer crashed", filename: null })],
    });
    expect(await screen.findByText(/No analyses yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run a scenario" })).toHaveAttribute("href", "/households/h1/scenarios");
    expect(await screen.findByRole("button", { name: /Download Liquidity report \(PDF\)/ })).toBeInTheDocument();
    expect(screen.getByText("Renderer crashed")).toBeInTheDocument();
  });
});
