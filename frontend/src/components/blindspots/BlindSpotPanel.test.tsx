import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { BlindSpotPanel } from "./BlindSpotPanel";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const empty = { items: [], total: 0, limit: 20, offset: 0 };

const report = {
  id: "bs1",
  household_id: "h1",
  scenario_id: "s1",
  engine_version: "1",
  as_of_date: "2026-10-16",
  risk_count: 2,
  blind_spot_count: 1,
  created_at: "2026-10-16T10:00:00Z",
  warnings: [],
  constraint_versions: [],
  result: {
    method: "Fixed deterministic variants.",
    disclaimer: "Deterministic what-if analysis under stated assumptions. It is not a forecast.",
    monthly_spending: 20000,
    summary: { variants: 3, risks: 2, blind_spots: 1, critical: 1 },
    risks: [
      {
        rank: 1,
        variant: "reit_suspended",
        label: "REIT redemptions suspended",
        tier: 1,
        changes: ["REIT board fill factor set to 0"],
        severity: "critical",
        blind_spot: true,
        first_shortfall_month: 4,
        shortfall_amount: 30000,
        peak_shortfall: 90000,
        peak_in_months_of_spending: 4.5,
        paper_wealth_first_shortfall_month: null,
        binding_in_first_shortfall_month: ["reit_quarterly_cap"],
        contributing_rules: [
          {
            rule: "reit_quarterly_cap",
            peak_shortfall_reduction: 60000,
            removes_shortfall: false,
            basis: "Relaxing the quarterly cap reduces the peak deficit.",
            evidence: [{ document: "Prospectus_2026.pdf", pdf_page: 12, quote: "limited to 5% of the aggregate NAV per quarter" }],
          },
        ],
      },
      {
        rank: 2,
        variant: "income_stop",
        label: "Income stops",
        tier: 1,
        changes: ["Income set to 0 from month 1"],
        severity: "moderate",
        blind_spot: false,
        first_shortfall_month: 15,
        shortfall_amount: 1000,
        peak_shortfall: 5000,
        peak_in_months_of_spending: 0.25,
        paper_wealth_first_shortfall_month: 15,
        binding_in_first_shortfall_month: [],
        contributing_rules: [],
      },
    ],
    comparison: [
      {
        variant: "baseline",
        label: "Baseline",
        changes: [],
        contract_aware: { first_shortfall_month: null, shortfall_amount: 0, peak_shortfall: 0, min_cash: 1000 },
        paper_wealth: { first_shortfall_month: null, shortfall_amount: 0, peak_shortfall: 0, min_cash: 5000 },
        monthly_cash: [1000, 2000],
        monthly_cash_paper_wealth: [1000, 2000],
      },
      {
        variant: "reit_suspended",
        label: "REIT redemptions suspended",
        changes: ["REIT board fill factor set to 0"],
        contract_aware: { first_shortfall_month: 4, shortfall_amount: 30000, peak_shortfall: 90000, min_cash: -90000 },
        paper_wealth: { first_shortfall_month: null, shortfall_amount: 0, peak_shortfall: 0, min_cash: 500 },
        monthly_cash: [1000, -5000],
        monthly_cash_paper_wealth: [1000, 500],
      },
    ],
  },
};

describe("BlindSpotPanel", () => {
  it("runs a check and renders the disclaimer, ranked risks and evidence", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url.startsWith(`${API}/households/h1/blind-spot-reports`)) return jsonResponse(empty);
      if (c.method === "POST" && c.url === `${API}/scenarios/s1/blind-spots`) return jsonResponse(report, 201);
      return undefined;
    });
    const user = userEvent.setup();
    render(<BlindSpotPanel householdId="h1" scenarioId="s1" currency="USD" canEdit />);
    await screen.findByText("No blind-spot report for this scenario yet.");
    await user.click(screen.getByRole("button", { name: "Run blind-spot check" }));

    expect(await screen.findByText(/It is not a forecast/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 variants run out of cash/)).toBeInTheDocument();
    const table = screen.getByRole("region", { name: "Ranked liquidity risks" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]!).getByText("REIT redemptions suspended")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Critical")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Blind spot")).toHaveAttribute("title", expect.stringMatching(/Not visible in a paper-wealth view/));
    expect(within(rows[1]!).getByText("$90,000")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Income stops")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Visible on paper")).toBeInTheDocument();

    await user.click(within(table).getByRole("button", { name: "Show details for REIT redemptions suspended" }));
    expect(screen.getByText(/limited to 5% of the aggregate NAV per quarter/)).toBeInTheDocument();
    expect(screen.getByText(/Prospectus_2026.pdf · PDF page 12/)).toBeInTheDocument();
    expect(screen.getByText("Relaxing the quarterly cap reduces the peak deficit.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scenario comparison" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("renders a term_conflict 409 as a conflict table", async () => {
    installFetch((c) => {
      if (c.method === "GET") return jsonResponse(empty);
      return errorResponse(409, "term_conflict", "Approved contract terms conflict", "req-77", {
        as_of_date: "2026-10-16",
        conflicts: [
          {
            term: "reit_quarterly_cap_pct",
            constraint_type: "redemption_limit",
            asset_key: "non_traded_reit",
            candidates: [
              { constraint_id: "c-aaaaaaaa1", value: 5, unit: "percent", document: "Prospectus_2025.pdf", pdf_page: 12, review_status: "confirmed" },
              { constraint_id: "c-bbbbbbbb2", value: 2, unit: "percent", document: "Supplement_2026.pdf", pdf_page: 3, review_status: "edited" },
            ],
          },
        ],
      });
    });
    const user = userEvent.setup();
    render(<BlindSpotPanel householdId="h1" scenarioId="s1" currency="USD" canEdit />);
    await screen.findByText("No blind-spot report for this scenario yet.");
    await user.click(screen.getByRole("button", { name: "Run blind-spot check" }));
    expect(await screen.findByText(/Approved contract terms disagree/)).toBeInTheDocument();
    const table = screen.getByRole("region", { name: "Conflicting approved terms" });
    expect(within(table).getByText("Prospectus_2025.pdf")).toBeInTheDocument();
    expect(within(table).getByText("Supplement_2026.pdf")).toBeInTheDocument();
    expect(within(table).getByText("REIT quarterly cap %")).toBeInTheDocument();
    expect(screen.getByText(/mark the newer term as superseding the older one/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fund Library" })).toHaveAttribute("href", "/funds");
  });
});
