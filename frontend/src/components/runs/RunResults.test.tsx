import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

import { buildChartData, RunResults } from "./RunResults";
import type { MonthOut, RunDetail } from "@/lib/types";

function month(model: string, m: number, ending: string, shortfall = "0.00"): MonthOut {
  return {
    model,
    month: m,
    label: `M${m}`,
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
  aware_summary: { model: "contract_aware", first_shortfall_month: 2, shortfall_amount: 250, peak_shortfall: 250, min_cash: -250 },
  liquidity: { window_months: 3, total: 12000, naive_total: 30000, cash: 1000 },
  warnings: ["Using default SBL advance rate"],
  created_at: "2026-02-01T10:00:00Z",
  inputs_snapshot: {},
  household_snapshot: {},
  terms: [
    { term: "interval_repurchase_pct", value: 0.05, provenance: "SYNTHETIC_Interval_Fund.pdf p.3", source_backed: true },
    { term: "sbl_advance_rate", value: 0.5, provenance: "default assumption", source_backed: false },
  ],
  constraint_versions: [],
  months: [
    month("contract_aware", 1, "1050.00"),
    month("contract_aware", 2, "-250.00", "250.00"),
    month("contract_aware", 3, "100.00"),
    month("naive", 1, "1050.00"),
    month("naive", 2, "300.00"),
    month("naive", 3, "450.00"),
  ],
};

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

describe("buildChartData", () => {
  it("joins both models per month from API rows", () => {
    expect(buildChartData(run.months)).toEqual([
      { month: 1, label: "M1", contract_aware: 1050, naive: 1050 },
      { month: 2, label: "M2", contract_aware: -250, naive: 300 },
      { month: 3, label: "M3", contract_aware: 100, naive: 450 },
    ]);
  });
});

describe("RunResults", () => {
  it("renders KPIs, chart lines, the monthly table and terms", async () => {
    const { container } = render(<RunResults run={run} householdId="h1" />);
    expect(screen.getByText("Month 2 · $250.00")).toBeInTheDocument();
    expect(screen.getByText("None in horizon")).toBeInTheDocument();
    expect(screen.getAllByText("$12,000").length).toBeGreaterThan(0);
    expect(screen.getByText("Using default SBL advance rate")).toBeInTheDocument();

    const lines = container.querySelectorAll(".recharts-line path.recharts-line-curve");
    expect(lines).toHaveLength(2);
    const dashed = [...lines].filter((l) => l.getAttribute("stroke-dasharray") === "6 4");
    expect(dashed).toHaveLength(1);
    expect(container.querySelector(".recharts-reference-line")).not.toBeNull();

    const table = screen.getByRole("region", { name: /Monthly cash flow, Contract-aware/ });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[2]!).getByText(`−$250.00`)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("interval_fund_gate")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Naive" }));
    const naiveTable = screen.getByRole("region", { name: /Monthly cash flow, Naive/ });
    expect(within(naiveTable).getByText("$450.00")).toBeInTheDocument();

    expect(screen.getByText("Default assumption")).toBeInTheDocument();
    expect(screen.getByText("Source-backed")).toBeInTheDocument();
    expect(screen.getByText(/1 term was not backed/)).toBeInTheDocument();
  });
});
