import { describe, expect, it } from "vitest";
import { householdWorkflow } from "./workflow";
import type { DocumentOut, RunSummary } from "./types";

const doc = (status: string, id = status) => ({ id, status }) as unknown as DocumentOut;
const counts = (o: Record<string, number> = {}) => ({
  assets: 0,
  cash_flows: 0,
  constraints_pending_review: 0,
  constraints_approved: 0,
  scenarios: 0,
  runs: 0,
  ...o,
});

describe("householdWorkflow", () => {
  it("starts at Profile for an empty household", () => {
    const { steps, next } = householdWorkflow({ householdId: "h1", counts: counts(), documents: [], latestRun: null, preventionPlans: 0, exports: 0 });
    expect(next?.key).toBe("profile");
    expect(steps.find((s) => s.key === "profile")!.state).toBe("current");
    expect(steps.find((s) => s.key === "results")!.state).toBe("blocked");
  });

  it("flags failed documents and pending terms as needing attention", () => {
    const { steps, next } = householdWorkflow({
      householdId: "h1",
      counts: counts({ assets: 2, cash_flows: 3, constraints_pending_review: 4 }),
      documents: [doc("extracted"), doc("failed")],
      latestRun: null,
      preventionPlans: 0,
      exports: 0,
    });
    expect(steps.find((s) => s.key === "documents")).toMatchObject({ state: "attention", detail: "2 agreements · 1 failed" });
    expect(steps.find((s) => s.key === "review")).toMatchObject({ state: "attention", href: "/households/h1/constraints?review_status=needs_review" });
    expect(next?.key).toBe("documents");
  });

  it("skips optional earlier steps once later work exists and points at the report", () => {
    const run = { id: "r1", scenario_id: "s1", aware_summary: { first_shortfall_month: 5 } } as unknown as RunSummary;
    const { steps, next } = householdWorkflow({
      householdId: "h1",
      counts: counts({ assets: 1, cash_flows: 1, constraints_approved: 0, scenarios: 1, runs: 1 }),
      documents: [],
      latestRun: run,
      preventionPlans: 1,
      exports: 0,
    });
    expect(steps.find((s) => s.key === "results")!.detail).toBe("Latest: shortfall from month 5");
    expect(next).toMatchObject({ key: "report", state: "current", href: "/households/h1/exports?run_id=r1" });
  });
});
