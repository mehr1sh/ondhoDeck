import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExplanationPanel, hasExplanation } from "./ExplanationPanel";
import type { RunExplanation } from "@/lib/types";

const explanation: RunExplanation = {
  method: "Deterministic explanation of a simulation result (no LLM).",
  first_shortfall_month: 4,
  shortfall_amount: 1200,
  peak_shortfall: 5000,
  binding_in_first_shortfall_month: ["REIT monthly cap 2%"],
  contributing_rules: [
    {
      rule: "Non-traded REIT redemption limits",
      relaxation: "reit_gate",
      peak_shortfall_reduction: 4000,
      removes_shortfall: true,
      first_shortfall_month_without_rule: null,
      terms: [{ term: "reit_monthly_cap_pct", value: 2, provenance: "approved constraint" }],
      evidence: [
        {
          id: "c1",
          revision: 2,
          type: "redemption_monthly_cap",
          asset_key: "non_traded_reit",
          document: "SYNTHETIC_REIT.pdf",
          pdf_page: 7,
          quote: "repurchases are limited to 2% of NAV per month",
          value: 2,
        },
      ],
      basis: "approved contract clauses",
    },
    {
      rule: "SBL collateral call",
      relaxation: "collateral_call",
      peak_shortfall_reduction: 500,
      removes_shortfall: false,
      first_shortfall_month_without_rule: 5,
      terms: [],
      evidence: [],
      basis: "default modelling assumption - no approved clause",
    },
  ],
  material_assumptions: [
    {
      assumption: "equity_drawdown",
      label: "Equity drawdown",
      base_value: 0.25,
      material: true,
      variants: [
        { direction: "lower", value: 0.2, first_shortfall_month: null, peak_shortfall: 0, material: true },
        { direction: "higher", value: 0.3, first_shortfall_month: 3, peak_shortfall: 9000, material: true },
      ],
    },
  ],
};

describe("ExplanationPanel", () => {
  it("renders the first shortfall, rules in order and evidence quotes with document and page", () => {
    const { container } = render(<ExplanationPanel explanation={explanation} currency="USD" />);
    expect(screen.getByText("Why this result")).toBeInTheDocument();
    expect(screen.getByText(/Counterfactual analysis of the deterministic model/)).toBeInTheDocument();
    expect(screen.getByText(/not advice or a forecast/)).toBeInTheDocument();
    expect(screen.getByText("Month 4")).toBeInTheDocument();
    expect(screen.getByText("REIT monthly cap 2%")).toBeInTheDocument();

    const rules = container.querySelectorAll("ol > li");
    expect(rules[0]).toHaveTextContent("Non-traded REIT redemption limits");
    expect(rules[1]).toHaveTextContent("SBL collateral call");
    expect(within(rules[0] as HTMLElement).getByText("$4,000")).toBeInTheDocument();
    expect(rules[0]).toHaveTextContent("Removing it removes the shortfall");
    expect(rules[0]).toHaveTextContent("Basis: approved contract clauses");
    expect(rules[1]).toHaveTextContent("Shortfall remains without it (month 5)");
    expect(rules[1]).toHaveTextContent("Basis: default modelling assumption - no approved clause");

    const quote = container.querySelector("blockquote");
    expect(quote).toHaveTextContent("repurchases are limited to 2% of NAV per month");
    expect(screen.getByText(/SYNTHETIC_REIT\.pdf · PDF page 7/)).toBeInTheDocument();

    expect(screen.getByRole("region", { name: "Assumption sensitivity" })).toHaveTextContent("Equity drawdown");
  });

  it("treats null and empty explanations of old runs as missing", () => {
    expect(hasExplanation(null)).toBe(false);
    expect(hasExplanation({})).toBe(false);
    expect(hasExplanation(explanation)).toBe(true);
  });
});
