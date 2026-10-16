/**
 * Display helpers for a run's headline answer. They only select and format values returned by
 * GET /runs/{id}; no simulation result is computed on the client.
 */
import { formatMoney, parseDecimal } from "@/lib/format";
import type { MonthOut, RunConstraintVersion, RunDetail } from "@/lib/types";

const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "M2 (Mar)" → 2 (zero-based calendar month index), or null. */
export function labelCalendarMonth(label: string | null | undefined): number | null {
  const m = /\(([A-Z][a-z]{2})\)/.exec(label ?? "");
  if (!m) return null;
  const i = SHORT_MONTHS.indexOf(m[1]!);
  return i >= 0 ? i : null;
}

/**
 * Calendar label for projection month `month`, e.g. "Mar 2027".
 * The month name comes from the API label. The year is added only when the run's as-of date
 * (household_snapshot.as_of_date, the date of projection month 1) falls in the same calendar
 * month as the label of month 1; otherwise only the month name is returned.
 */
export function calendarLabel(run: Pick<RunDetail, "months" | "household_snapshot">, month: number): string | null {
  const rows = run.months.filter((r) => r.model === "contract_aware");
  const row = rows.find((r) => r.month === month) ?? run.months.find((r) => r.month === month);
  const cal = labelCalendarMonth(row?.label);
  if (cal === null) return null;
  const first = rows.find((r) => r.month === 1) ?? run.months.find((r) => r.month === 1);
  const firstCal = labelCalendarMonth(first?.label);
  const asOf = typeof run.household_snapshot?.as_of_date === "string" ? run.household_snapshot.as_of_date : null;
  const match = asOf ? /^(\d{4})-(\d{2})-\d{2}$/.exec(asOf) : null;
  if (match && firstCal !== null && Number(match[2]) - 1 === firstCal) {
    const year = Number(match[1]) + Math.floor((firstCal + month - 1) / 12);
    return `${SHORT_MONTHS[cal]} ${year}`;
  }
  return SHORT_MONTHS[cal]!;
}

export function monthPhrase(run: Pick<RunDetail, "months" | "household_snapshot">, month: number): string {
  const cal = calendarLabel(run, month);
  return cal ? `Month ${month} (${cal})` : `Month ${month}`;
}

export function hasShortfall(summary: RunDetail["aware_summary"]): boolean {
  return summary.first_shortfall_month !== null && summary.first_shortfall_month !== undefined;
}

/** The one-sentence answer for the contract-aware model. */
export function answerSentence(run: RunDetail): string {
  const s = run.aware_summary;
  if (!hasShortfall(s)) return `No projected shortfall over the ${run.horizon_months}-month horizon.`;
  return `Projected shortfall of ${formatMoney(s.shortfall_amount, run.reporting_currency)} in ${monthPhrase(run, s.first_shortfall_month as number)}.`;
}

/** Contiguous [start, end] month ranges where the contract-aware model reports a shortfall. */
export function shortfallRanges(months: MonthOut[]): Array<[number, number]> {
  const short = months
    .filter((m) => m.model === "contract_aware" && (parseDecimal(m.shortfall) ?? 0) > 0)
    .map((m) => m.month)
    .sort((a, b) => a - b);
  const out: Array<[number, number]> = [];
  for (const m of short) {
    const last = out[out.length - 1];
    if (last && m === last[1] + 1) last[1] = m;
    else out.push([m, m]);
  }
  return out;
}

/** constraint_versions entries as typed records (the API types them loosely). */
export function constraintVersions(run: Pick<RunDetail, "constraint_versions">): RunConstraintVersion[] {
  return (run.constraint_versions ?? []).filter(
    (v): v is RunConstraintVersion & Record<string, unknown> => typeof v === "object" && v !== null && typeof v.id === "string",
  );
}

/** Where to see the evidence for a term version: library terms on the fund page, household terms on their own page. */
export function evidenceHref(householdId: string, id: string, version: RunConstraintVersion | undefined): string {
  if (version?.owner === "fund" && version.fund_id) return `/funds/${version.fund_id}`;
  return `/households/${householdId}/constraints/${id}`;
}

/** Chart palette drawn from the design tokens. Series are also distinguished by dash pattern. */
export const CHART = {
  aware: "#1F4A36",
  naive: "#646B76",
  alt: "#8A5A12",
  zero: "#1E2430",
  grid: "#E3E1DB",
  rule: "#CFCCC4",
  axis: "#3C4350",
  shortfallFill: "#F8ECEA",
  shortfallStroke: "#9B2C2C",
} as const;
