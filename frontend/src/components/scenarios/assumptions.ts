/**
 * Conversion between scenario assumption values (API units) and form input strings.
 *
 * Unit convention for `percent` fields: keys ending in `_pct` are already expressed in percent
 * units (e.g. reit_base_demand_pct = 1.5 means 1.5%); every other percent field is a fraction
 * (equity_drawdown = 0.25 means 25%) and is edited as a percentage.
 */
import type { AssumptionField } from "@/lib/types";

export const SPECIAL_KEYS = new Set(["fx_rates", "assumption_sources"]);

export function isFractionPercent(field: Pick<AssumptionField, "key" | "kind">): boolean {
  return field.kind === "percent" && !field.key.endsWith("_pct");
}

function round(n: number): number {
  return Number(n.toPrecision(12));
}

export function scalarToInput(field: Pick<AssumptionField, "key" | "kind">, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (field.kind === "list") return Array.isArray(value) ? value.join(", ") : String(value);
  if (typeof value === "number") return String(isFractionPercent(field) ? round(value * 100) : value);
  return String(value);
}

export type ParseResult = { ok: true; value: unknown } | { ok: false; error: string };

export function inputToScalar(field: Pick<AssumptionField, "key" | "kind">, input: string): ParseResult {
  const s = input.trim().replace(/,(?=\d{3}\b)/g, "");
  if (field.kind === "list") {
    if (!input.trim()) return { ok: true, value: [] };
    const parts = input.split(/[,\s]+/).filter(Boolean);
    const nums = parts.map((p) => Number(p));
    if (nums.some((n) => !Number.isInteger(n) || n < 1)) {
      return { ok: false, error: "Enter whole month numbers separated by commas, e.g. 2, 5, 8." };
    }
    return { ok: true, value: nums };
  }
  if (!s) return { ok: false, error: "Enter a value." };
  const n = Number(s);
  if (!Number.isFinite(n)) return { ok: false, error: "Enter a number." };
  if (n < 0) return { ok: false, error: "Must not be negative." };
  return { ok: true, value: isFractionPercent(field) ? round(n / 100) : n };
}

/** Groups fields preserving first-appearance order of groups. */
export function groupFields(fields: AssumptionField[]): Array<{ group: string; fields: AssumptionField[] }> {
  const out: Array<{ group: string; fields: AssumptionField[] }> = [];
  for (const f of fields) {
    if (SPECIAL_KEYS.has(f.key)) continue;
    let g = out.find((x) => x.group === f.group);
    if (!g) {
      g = { group: f.group, fields: [] };
      out.push(g);
    }
    g.fields.push(f);
  }
  return out;
}

export function unitSuffix(field: Pick<AssumptionField, "kind">): string {
  switch (field.kind) {
    case "percent":
      return "%";
    case "months":
      return "months";
    default:
      return "";
  }
}
