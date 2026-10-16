/**
 * Deterministic "what needs attention" logic for the Overview page.
 *
 * Every action is derived only from API data that is already loaded (households, review queue,
 * scenarios with their latest run, documents). Nothing here invents numbers: counts are lengths of
 * the loaded lists and money values are passed through untouched for display.
 */
import type { DocumentOut, HouseholdOut, ReviewQueueOut, ScenarioListItem } from "@/lib/types";

export type ActionKind =
  | "create_household"
  | "failed_documents"
  | "processing_documents"
  | "review_terms"
  | "run_scenario"
  | "open_shortfall"
  | "all_current";

export interface OverviewAction {
  kind: ActionKind;
  title: string;
  reason: string;
  href: string;
  cta: string;
  tone: "neutral" | "attention" | "risk";
}

export interface OverviewData {
  households: HouseholdOut[];
  review: ReviewQueueOut | null;
  scenarios: ScenarioListItem[];
  documents: DocumentOut[];
}

export const PROCESSING_STATUSES = new Set(["pending_upload", "uploaded", "queued", "processing"]);

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function docHref(d: DocumentOut): string {
  return d.household_id ? `/households/${d.household_id}/documents/${d.id}` : d.fund_id ? `/funds/${d.fund_id}` : "/documents";
}

/** Scenarios whose latest run projects a shortfall, earliest first shortfall month first. */
export function projectedShortfalls(scenarios: ScenarioListItem[]): ScenarioListItem[] {
  return scenarios
    .filter((s) => s.latest_run_id && s.latest_first_shortfall_month !== null && s.latest_first_shortfall_month !== undefined)
    .sort(
      (a, b) =>
        (a.latest_first_shortfall_month as number) - (b.latest_first_shortfall_month as number) ||
        a.household_name.localeCompare(b.household_name),
    );
}

/** Scenarios that have been run, most recent run first. */
export function recentAnalyses(scenarios: ScenarioListItem[]): ScenarioListItem[] {
  return scenarios
    .filter((s) => s.latest_run_id && s.latest_run_at)
    .sort((a, b) => (b.latest_run_at ?? "").localeCompare(a.latest_run_at ?? ""));
}

/**
 * All outstanding actions in priority order. The first one is the "Next action".
 * Order: no households → failed documents → documents still processing → terms awaiting review →
 * households with extracted documents but no analysis → projected shortfalls → all current.
 */
export function deriveActions(data: OverviewData): OverviewAction[] {
  const { households, review, scenarios, documents } = data;
  if (households.length === 0) {
    return [
      {
        kind: "create_household",
        title: "Create a household",
        reason: "There are no households yet. Add one to record assets, obligations and private agreements.",
        href: "/households/new",
        cta: "Create household",
        tone: "neutral",
      },
    ];
  }

  const actions: OverviewAction[] = [];
  const failed = documents.filter((d) => d.status === "failed");
  if (failed.length) {
    const first = failed[0]!;
    actions.push({
      kind: "failed_documents",
      title: failed.length === 1 ? `Resolve the failed document ${first.original_filename}` : `Resolve ${plural(failed.length, "failed document")}`,
      reason: first.error_message
        ? `Processing failed: ${first.error_message}`
        : "Processing failed. Open the document to see the error and retry.",
      href: docHref(first),
      cta: "Open document",
      tone: "risk",
    });
  }

  const processing = documents.filter((d) => PROCESSING_STATUSES.has(d.status));
  if (processing.length) {
    const first = processing[0]!;
    actions.push({
      kind: "processing_documents",
      title:
        processing.length === 1
          ? `Check ${first.original_filename}, still processing`
          : `${plural(processing.length, "document")} still processing`,
      reason: "Extracted terms become reviewable once processing finishes.",
      href: docHref(first),
      cta: "Open document",
      tone: "neutral",
    });
  }

  if (review && review.total > 0) {
    actions.push({
      kind: "review_terms",
      title: `Review ${plural(review.total, "extracted term")}`,
      reason: `${review.household_items} from household agreements and ${review.library_items} from the Fund Library. Only approved terms are used in analyses.`,
      href: "/review",
      cta: "Open Review Queue",
      tone: "attention",
    });
  }

  const analysed = new Set(scenarios.filter((s) => s.latest_run_id).map((s) => s.household_id));
  const withExtracted = new Set(
    documents.filter((d) => d.household_id && d.status === "extracted").map((d) => d.household_id as string),
  );
  const needsRun = households.filter((h) => withExtracted.has(h.id) && !analysed.has(h.id));
  for (const h of needsRun) {
    const hasScenario = scenarios.find((s) => s.household_id === h.id);
    actions.push({
      kind: "run_scenario",
      title: `Run a liquidity scenario for ${h.name}`,
      reason: hasScenario
        ? `The scenario “${hasScenario.name}” has not been run yet.`
        : "Its documents are extracted but no scenario has been created or run.",
      href: hasScenario ? `/households/${h.id}/scenarios/${hasScenario.id}` : `/households/${h.id}/scenarios`,
      cta: hasScenario ? "Open scenario" : "Create scenario",
      tone: "neutral",
    });
  }

  const shortfalls = projectedShortfalls(scenarios);
  if (shortfalls.length) {
    const s = shortfalls[0]!;
    actions.push({
      kind: "open_shortfall",
      title: `Open the analysis for ${s.household_name}: shortfall projected in month ${s.latest_first_shortfall_month}`,
      reason: `Latest run of “${s.name}”.${shortfalls.length > 1 ? ` ${plural(shortfalls.length - 1, "other scenario")} also ${shortfalls.length - 1 === 1 ? "projects" : "project"} a shortfall.` : ""}`,
      href: `/households/${s.household_id}/runs/${s.latest_run_id}`,
      cta: "Open analysis",
      tone: "risk",
    });
  }

  if (!actions.length) {
    actions.push({
      kind: "all_current",
      title: "Nothing needs attention",
      reason: analysed.size
        ? "No failed or pending documents, no terms awaiting review, and no projected shortfalls in the latest runs."
        : "No documents or analyses are pending. Upload a household agreement or create a scenario to begin.",
      href: analysed.size ? "/scenarios" : "/households",
      cta: analysed.size ? "View liquidity scenarios" : "Open households",
      tone: "neutral",
    });
  }
  return actions;
}
