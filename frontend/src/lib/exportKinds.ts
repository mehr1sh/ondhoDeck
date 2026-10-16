import { humanize } from "@/lib/format";

/** Human labels for export kinds (backend ExportKind). */
export const EXPORT_KIND_LABELS: Record<string, string> = {
  constraints_csv: "Terms (CSV)",
  constraints_json: "Terms (JSON)",
  simulation_csv: "Monthly projection (CSV)",
  results_json: "Analysis results (JSON)",
  report_pdf: "Liquidity report (PDF)",
  blind_spot_pdf: "Blind-spot report (PDF)",
};

export function exportKindLabel(kind: string): string {
  return EXPORT_KIND_LABELS[kind] ?? humanize(kind);
}
