import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

vi.mock("recharts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={{ width: 800, height: 320 }}>
        {isValidElement(children) ? cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 320 }) : children}
      </div>
    ),
  };
});

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

import { buildChartData, RunResults } from "./RunResults";
import { answerSentence, calendarLabel } from "./answer";
import type { MonthOut, RunDetail, RunExplanation, RunSummary } from "@/lib/types";

const CAL = ["Feb", "Mar", "Apr"];

function month(model: string, m: number, ending: string, shortfall = "0.00"): MonthOut {
  return {
    model,
    month: m,
    label: `M${m} (${CAL[m - 1]})`,
    beginning_cash: "1000.00",
    income: "500.00",
    expenses: "400.00",
    taxes: "0.00",
    debt_service: "50.00",
    collateral_call: "0.00",
    capital_call: m === 2 ? "900.00" : "0.00",
    redemption_requested: "0.00",
    redemption_proceeds: "0.00",
    other_proceeds: "0.00",
    ending_cash: ending,
    shortfall,
    reit_fill_rate: null,
    binding_constraints: m === 2 && model === "contract_aware" ? ["interval_fund_gate"] : [],
  };
}

const run: RunDetail = {
  id: "r1",
  household_id: "h1",
  scenario_id: "s1",
  scenario_name: "Base case",
  engine_version: "1.2.0",
  reporting_currency: "USD",
  horizon_months: 3,
  naive_summary: { model: "naive", first_shortfall_month: null, shortfall_amount: 0, peak_shortfall: 0, min_cash: 300 },
  aware_summary: { model: "contract_aware", first_shortfall_month: 2, shortfall_amount: 250, peak_shortfall: 275, min_cash: -260 },
  liquidity: { window_months: 3, total: 12000, naive_total: 30000, cash: 1000 },
  warnings: ["Using default SBL advance rate"],
  created_at: "2026-02-01T10:00:00Z",
  inputs_snapshot: { equity_drawdown: 0.25, horizon_months: 3 },
  household_snapshot: { as_of_date: "2026-02-01" },
  terms: [
    { term: "interval_repurchase_pct", value: 0.05, provenance: "SYNTHETIC_Interval_Fund.pdf p.3", source_backed: true },
    { term: "sbl_advance_rate", value: 0.5, provenance: "default assumption", source_backed: false },
  ],
  constraint_versions: [
    { id: "c1", revision: 2, type: "redemption_monthly_cap", asset_key: "non_traded_reit", value: "2", document: "SYNTHETIC_REIT.pdf", pdf_page: 7, owner: "household", fund_id: null, effective_from: null, effective_to: null },
    { id: "c9", revision: 1, type: "repurchase_pct", asset_key: "interval_fund", value: "5", document: "Interval_Prospectus.pdf", pdf_page: 12, owner: "fund", fund_id: "f9", effective_from: "2026-01-01", effective_to: null },
  ],
  explanation: {
    method: "Deterministic counterfactual.",
    first_shortfall_month: 2,
    shortfall_amount: 250,
    peak_shortfall: 275,
    binding_in_first_shortfall_month: ["Interval fund gate"],
    contributing_rules: [
      {
        rule: "Non-traded REIT redemption limits",
        relaxation: "reit_gate",
        peak_shortfall_reduction: 4000,
        removes_shortfall: true,
        first_shortfall_month_without_rule: null,
        terms: [{ term: "reit_monthly_cap_pct", value: 2, provenance: "approved constraint" }],
        evidence: [
          { id: "c1", revision: 2, type: "redemption_monthly_cap", asset_key: "non_traded_reit", document: "SYNTHETIC_REIT.pdf", pdf_page: 7, quote: "repurchases are limited to 2% of NAV per month", value: 2 },
        ],
        basis: "approved contract clauses",
      },
      {
        rule: "Interval fund repurchase offers",
        relaxation: "interval_gate",
        peak_shortfall_reduction: 1500,
        removes_shortfall: false,
        first_shortfall_month_without_rule: 3,
        terms: [{ term: "interval_repurchase_pct", value: 0.05, provenance: "library" }],
        evidence: [
          { id: "c9", revision: 1, type: "repurchase_pct", asset_key: "interval_fund", document: "Interval_Prospectus.pdf", pdf_page: 12, quote: "offers to repurchase 5% of outstanding shares", value: 5 },
        ],
        basis: "approved contract clauses",
      },
    ],
    material_assumptions: [],
  },
  months: [
    month("contract_aware", 1, "1050.00"),
    month("contract_aware", 2, "-260.00", "250.00"),
    month("contract_aware", 3, "100.00"),
    month("naive", 1, "1050.00"),
    month("naive", 2, "300.00"),
    month("naive", 3, "450.00"),
  ],
};

const noShortfall: RunDetail = {
  ...run,
  id: "r2",
  scenario_id: "s2",
  scenario_name: "Mild drawdown",
  created_at: "2026-02-03T10:00:00Z",
  aware_summary: { model: "contract_aware", first_shortfall_month: null, shortfall_amount: 0, peak_shortfall: 0, min_cash: 4321 },
  explanation: { ...(run.explanation as RunExplanation), first_shortfall_month: null, contributing_rules: [] },
  months: [
    month("contract_aware", 1, "5000.00"),
    month("contract_aware", 2, "4321.00"),
    month("contract_aware", 3, "4800.00"),
    month("naive", 1, "5000.00"),
    month("naive", 2, "4600.00"),
    month("naive", 3, "4900.00"),
  ],
};

function summary(r: RunDetail): RunSummary {
  return {
    id: r.id,
    household_id: r.household_id,
    scenario_id: r.scenario_id,
    scenario_name: r.scenario_name,
    engine_version: r.engine_version,
    reporting_currency: r.reporting_currency,
    horizon_months: r.horizon_months,
    naive_summary: r.naive_summary,
    aware_summary: r.aware_summary,
    liquidity: r.liquidity,
    warnings: r.warnings,
    created_at: r.created_at,
  };
}

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

function mockApi() {
  return installFetch((c) => {
    if (c.method === "GET" && c.url.startsWith(`${API}/households/h1/runs`)) {
      return jsonResponse({ items: [summary(run), summary(noShortfall)], total: 2, limit: 50, offset: 0 });
    }
    if (c.method === "GET" && c.url === `${API}/runs/r2`) return jsonResponse(noShortfall);
    return undefined;
  });
}

describe("buildChartData", () => {
  it("joins both models per month from API rows", () => {
    expect(buildChartData(run.months)).toEqual([
      { month: 1, label: "M1 (Feb)", contract_aware: 1050, naive: 1050 },
      { month: 2, label: "M2 (Mar)", contract_aware: -260, naive: 300 },
      { month: 3, label: "M3 (Apr)", contract_aware: 100, naive: 450 },
    ]);
  });
});

describe("answer helpers", () => {
  it("adds the year only when the as-of date matches month 1", () => {
    expect(calendarLabel(run, 2)).toBe("Mar 2026");
    expect(calendarLabel({ ...run, household_snapshot: { as_of_date: "2026-07-01" } }, 2)).toBe("Mar");
    expect(calendarLabel({ ...run, household_snapshot: {} }, 2)).toBe("Mar");
  });
});

describe("RunResults", () => {
  it("answers first: shortfall sentence, peak deficit, lowest cash and a disclosure", () => {
    mockApi();
    const { container } = render(<RunResults run={run} householdId="h1" />);
    expect(screen.getByTestId("run-answer")).toHaveTextContent("Projected shortfall of $250.00 in Month 2 (Mar 2026).");
    expect(answerSentence(run)).toBe("Projected shortfall of $250.00 in Month 2 (Mar 2026).");
    const answer = screen.getByTestId("run-answer").closest("section")!;
    expect(within(answer).getByText("$275.00")).toBeInTheDocument();
    expect(within(answer).getByText("−$260.00")).toBeInTheDocument();
    expect(within(answer).getByText("No shortfall in horizon")).toBeInTheDocument();
    expect(answer).toHaveTextContent("Modelled projection — not a guaranteed outcome");
    // The answer block precedes the chart.
    const sections = [...container.querySelectorAll("h2")].map((h) => h.textContent);
    expect(sections.indexOf("Monthly cash")).toBeGreaterThan(-1);
    expect(sections.indexOf("Contributing terms")).toBeGreaterThan(sections.indexOf("Monthly cash"));
    expect(sections.indexOf("Scenario comparison")).toBeGreaterThan(sections.indexOf("Contributing terms"));
    expect(sections.indexOf("Assumptions and limitations")).toBeGreaterThan(sections.indexOf("Scenario comparison"));
  });

  it("states when there is no projected shortfall", () => {
    mockApi();
    render(<RunResults run={noShortfall} householdId="h1" />);
    expect(screen.getByTestId("run-answer")).toHaveTextContent("No projected shortfall over the 3-month horizon.");
    expect(screen.getByText("There is no shortfall to attribute. The terms applied are listed below.")).toBeInTheDocument();
  });

  it("draws both models with a zero line, marks shortfall months and offers a data table", async () => {
    mockApi();
    const { container } = render(<RunResults run={run} householdId="h1" />);
    const lines = container.querySelectorAll(".recharts-line path.recharts-line-curve");
    expect(lines).toHaveLength(2);
    expect([...lines].filter((l) => l.getAttribute("stroke-dasharray") === "6 4")).toHaveLength(1);
    expect(container.querySelector(".recharts-reference-line")).not.toBeNull();
    expect(container.querySelector(".recharts-reference-area")).not.toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Show chart data table" }));
    const data = screen.getByRole("region", { name: "Chart data: month-end cash" });
    expect(within(data).getAllByRole("row")).toHaveLength(4);
    expect(within(data).getByText("−$260.00")).toBeInTheDocument();
  });

  it("lists contributing terms with document, PDF page, revision, owner and evidence links", () => {
    mockApi();
    render(<RunResults run={run} householdId="h1" />);
    const table = screen.getByRole("region", { name: "Contributing terms table" });
    const rows = within(table).getAllByTestId("contributing-rule");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Non-traded REIT redemption limits");
    expect(rows[0]).toHaveTextContent("Peak falls by $4,000");
    expect(rows[0]).toHaveTextContent("Relaxing it removes the shortfall");
    expect(rows[0]).toHaveTextContent("SYNTHETIC_REIT.pdf · PDF page 7 · revision 2");
    expect(rows[0]).toHaveTextContent("Household");
    expect(rows[0]).toHaveTextContent("repurchases are limited to 2% of NAV per month");
    expect(within(rows[0]!).getByRole("link", { name: /View evidence/ })).toHaveAttribute("href", "/households/h1/constraints/c1");

    expect(rows[1]).toHaveTextContent("Shortfall remains without it (month 3)");
    expect(rows[1]).toHaveTextContent("Interval_Prospectus.pdf · PDF page 12 · revision 1");
    expect(rows[1]).toHaveTextContent("Library");
    expect(rows[1]).toHaveTextContent(/in force Jan 1, 2026 – open-ended/);
    expect(within(rows[1]!).getByRole("link", { name: /View evidence/ })).toHaveAttribute("href", "/funds/f9");
  });

  it("shows assumptions, warnings, defaults and limitations", () => {
    mockApi();
    render(<RunResults run={run} householdId="h1" />);
    expect(screen.getByText("Using default SBL advance rate")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Assumptions used" })).toHaveTextContent("Equity drawdown");
    const defaults = screen.getByRole("heading", { name: "Defaults used" }).parentElement!;
    expect(defaults).toHaveTextContent("SBL advance rate: 0.5 (default assumption)");
    expect(defaults).not.toHaveTextContent("Interval repurchase pct");
    expect(screen.getByText(/Deterministic model/)).toBeInTheDocument();
    expect(screen.getByText(/one interval-fund allocation/)).toBeInTheDocument();
    expect(screen.getByText(/resolved once, at the projection start date/)).toBeInTheDocument();
    expect(screen.getByText(/not investment, tax or legal advice/)).toBeInTheDocument();
    expect(screen.getByText(/1 term was not backed/)).toBeInTheDocument();
  });

  it("keeps the monthly detail table with a model switch", async () => {
    mockApi();
    render(<RunResults run={run} householdId="h1" />);
    const table = screen.getByRole("region", { name: /Monthly cash flow, Contract-aware/ });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[2]!).getByText("interval_fund_gate")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Paper-wealth (naive)" }));
    expect(within(screen.getByRole("region", { name: /Monthly cash flow, Paper-wealth/ })).getByText("$450.00")).toBeInTheDocument();
  });

  it("loads another run of the household for comparison", async () => {
    const { calls } = mockApi();
    const user = userEvent.setup();
    const { container } = render(<RunResults run={run} householdId="h1" />);
    const select = await screen.findByLabelText("Compare with");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
    await user.selectOptions(select, "r2");
    const table = await screen.findByRole("region", { name: "Run comparison" });
    const peak = within(table).getByRole("row", { name: /Peak shortfall/ });
    expect(peak).toHaveTextContent("$275.00");
    expect(peak).toHaveTextContent("$0.00");
    const low = within(table).getByRole("row", { name: /Lowest month-end cash/ });
    expect(low).toHaveTextContent("−$260.00");
    expect(low).toHaveTextContent("$4,321");
    expect(within(table).getByRole("row", { name: /First shortfall/ })).toHaveTextContent("None in horizon");
    expect(calls.some((c) => c.url === `${API}/runs/r2`)).toBe(true);
    expect(container.querySelectorAll("figure[aria-label^='Contract-aware ending cash by month'] .recharts-line")).toHaveLength(2);
  });
});

describe("RunResults evidence limits", () => {
  it("lists unmodelled and unsupported approved terms and labels derived values", () => {
    mockApi();
    const withLimits: RunDetail = {
      ...run,
      terms: [
        ...run.terms,
        { term: "reit_settlement_lag_months", value: 1, provenance: "derived from BREIT.pdf p.247 (confirmed)", source_backed: false, basis: "derived_from_clause" },
      ],
      explanation: {
        ...(run.explanation as RunExplanation),
        not_modelled: [
          { id: "b1", revision: 2, type: "board_discretion", asset_key: "non_traded_reit", document: "BREIT.pdf", pdf_page: 270, quote: "We may choose to repurchase fewer shares", value: null, reason: "Qualitative restriction: shown as a risk; the engine applies no numerical effect for it." },
        ],
        excluded_unsupported: [{ constraint_id: "x1", type: "redemption_monthly_cap", document: "BREIT.pdf", pdf_page: 99, reasons: ["value_not_in_quote"] }],
      },
    };
    render(<RunResults run={withLimits} householdId="h1" />);
    expect(screen.getByText("Approved terms not modelled numerically")).toBeInTheDocument();
    expect(screen.getByText(/the engine applies no numerical effect for it/)).toBeInTheDocument();
    expect(screen.getByText(/Approved terms not used: evidence does not support them/)).toBeInTheDocument();
    expect(screen.getByText(/Value not in quote/)).toBeInTheDocument();
    expect(screen.getAllByText("Derived from clause").length).toBeGreaterThan(0);
  });
});
