/**
 * Household workflow progress (Profile → Documents → Review terms → Scenario → Results → Prevention → Report).
 * Each step's state is computed only from API data: summary counts, document statuses, prevention plans and
 * exports. Nothing is assumed complete without a record that shows it.
 */
import type { WorkflowStep } from "@/components/ui";
import type { DocumentOut, RunSummary } from "@/lib/types";

export interface WorkflowInput {
  householdId: string;
  counts: Record<string, number>;
  documents: DocumentOut[];
  latestRun: RunSummary | null | undefined;
  preventionPlans: number;
  exports: number;
}

const n = (c: Record<string, number>, k: string) => (typeof c[k] === "number" ? c[k]! : 0);
const plural = (x: number, one: string, many = `${one}s`) => `${x} ${x === 1 ? one : many}`;

export function householdWorkflow(input: WorkflowInput): { steps: WorkflowStep[]; next: WorkflowStep | null } {
  const { counts, documents, latestRun } = input;
  const base = `/households/${input.householdId}`;
  const assets = n(counts, "assets");
  const flows = n(counts, "cash_flows");
  const pending = n(counts, "constraints_pending_review");
  const approved = n(counts, "constraints_approved");
  const scenarios = n(counts, "scenarios");
  const runs = n(counts, "runs");
  const live = documents.filter((d) => d.status !== "deleted");
  const failed = live.filter((d) => d.status === "failed").length;
  const processing = live.filter((d) => ["pending_upload", "uploaded", "queued", "processing"].includes(d.status)).length;
  const extracted = live.filter((d) => d.status === "extracted").length;
  const firstShortfall = latestRun?.aware_summary?.first_shortfall_month;
  const hasShortfall = typeof firstShortfall === "number";

  const steps: WorkflowStep[] = [
    {
      key: "profile",
      label: "Profile",
      state: assets > 0 && flows > 0 ? "done" : assets > 0 || flows > 0 ? "attention" : "todo",
      detail: `${plural(assets, "asset")} · ${plural(flows, "cash flow")}`,
      href: `${base}/profile`,
    },
    {
      key: "documents",
      label: "Documents",
      state: failed > 0 ? "attention" : processing > 0 ? "attention" : extracted > 0 ? "done" : "todo",
      detail: live.length
        ? [
            `${plural(live.length, "agreement")}`,
            failed ? `${failed} failed` : null,
            processing ? `${processing} processing` : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : "No agreements uploaded",
      href: `${base}/documents`,
    },
    {
      key: "review",
      label: "Review terms",
      state: pending > 0 ? "attention" : approved > 0 ? "done" : live.length ? "todo" : "blocked",
      detail: `${approved} approved · ${pending} awaiting review`,
      href: pending > 0 ? `${base}/constraints?review_status=needs_review` : `${base}/constraints`,
    },
    {
      key: "scenario",
      label: "Scenario",
      state: scenarios > 0 ? "done" : "todo",
      detail: plural(scenarios, "scenario"),
      href: `${base}/scenarios`,
    },
    {
      key: "results",
      label: "Results",
      state: runs > 0 ? "done" : scenarios > 0 ? "todo" : "blocked",
      detail: !latestRun
        ? plural(runs, "run")
        : hasShortfall
          ? `Latest: shortfall from month ${firstShortfall}`
          : "Latest: no shortfall in horizon",
      href: latestRun ? `${base}/runs/${latestRun.id}` : `${base}/scenarios`,
    },
    {
      key: "prevention",
      label: "Prevention",
      state: input.preventionPlans > 0 ? "done" : runs > 0 ? "todo" : "blocked",
      detail:
        input.preventionPlans > 0
          ? plural(input.preventionPlans, "plan")
          : latestRun && !hasShortfall
            ? "Optional: latest run shows no shortfall"
            : "No plan yet",
      href: latestRun ? `${base}/scenarios/${latestRun.scenario_id}/prevention` : `${base}/scenarios`,
    },
    {
      key: "report",
      label: "Report",
      state: input.exports > 0 ? "done" : runs > 0 ? "todo" : "blocked",
      detail: input.exports > 0 ? plural(input.exports, "export") : "No report yet",
      href: latestRun ? `${base}/exports?run_id=${latestRun.id}` : `${base}/exports`,
    },
  ];

  // A step still "todo" after a later step is complete was skipped (e.g. no private agreements because all
  // holdings use Fund Library terms); it is not offered as the next step.
  const laterDone = (i: number) => steps.slice(i + 1).some((s) => s.state === "done");
  const nextIdx = steps.findIndex((s, i) => s.state === "attention" || (s.state === "todo" && !laterDone(i)));
  if (nextIdx >= 0 && steps[nextIdx]!.state === "todo") steps[nextIdx] = { ...steps[nextIdx]!, state: "current" };
  return { steps, next: nextIdx >= 0 ? steps[nextIdx]! : null };
}
