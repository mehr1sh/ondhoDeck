"use client";

import Link from "next/link";
import { Badge, TableWrap, cx, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { EMPTY, formatDate, formatMoney, humanize } from "@/lib/format";
import type { ContributingRule, RunConstraintVersion } from "@/lib/types";
import { evidenceHref } from "./answer";
import { formatValue } from "./ExplanationPanel";

function effectiveWindow(v: RunConstraintVersion | undefined): string | null {
  if (!v || (!v.effective_from && !v.effective_to)) return null;
  return `in force ${v.effective_from ? formatDate(v.effective_from) : "from the start"} – ${v.effective_to ? formatDate(v.effective_to) : "open-ended"}`;
}

function Citation({ ev, version, householdId }: { ev: ContributingRule["evidence"][number]; version: RunConstraintVersion | undefined; householdId: string }) {
  const owner = version?.owner === "fund" ? "Library" : "Household";
  const window = effectiveWindow(version);
  return (
    <figure className="space-y-1">
      <figcaption className="text-xs text-ink-2">
        <span className="font-medium">{ev.document || "Document"}</span> · PDF page {ev.pdf_page} · revision {ev.revision} ·{" "}
        <Badge tone={owner === "Library" ? "info" : "neutral"}>{owner}</Badge>
        {window && <span className="block text-ink-3">{window}</span>}
      </figcaption>
      {ev.quote && (
        <blockquote className="evidence-quote line-clamp-4 border-l-2 border-accent bg-surface-muted px-3 py-1.5" title={ev.quote}>
          “{ev.quote}”
        </blockquote>
      )}
      <Link href={evidenceHref(householdId, ev.id, version)} className="text-xs font-medium text-accent-ink underline underline-offset-2">
        View evidence
        <span className="sr-only">
          {" "}
          for {humanize(ev.type)} on PDF page {ev.pdf_page}
        </span>
      </Link>
    </figure>
  );
}

/**
 * Contract terms that drove the shortfall, from explanation.contributing_rules. The contribution
 * is the API's counterfactual: how much the peak shortfall falls when the rule is relaxed.
 */
export function ContributingTerms({
  rules,
  versions,
  householdId,
  currency,
}: {
  rules: ContributingRule[];
  versions: RunConstraintVersion[];
  householdId: string;
  currency: string;
}) {
  const byId = new Map(versions.map((v) => [v.id, v] as const));
  return (
    <TableWrap label="Contributing terms table">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={th}>Term</th>
            <th className={thNum}>Value</th>
            <th className={thNum}>Contribution</th>
            <th className={th}>Basis</th>
            <th className={th}>Citation</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {rules.map((r) => {
            const backed = r.evidence.length > 0;
            return (
              <tr key={r.relaxation} data-testid="contributing-rule">
                <td className={cx(td, "min-w-44")}>
                  <span className="font-medium text-ink">{r.rule}</span>
                </td>
                <td className={tdNum}>
                  {r.terms.length ? (
                    <dl className="space-y-0.5">
                      {r.terms.map((t) => (
                        <div key={t.term} className="flex justify-end gap-2 whitespace-nowrap">
                          <dt className="text-xs font-normal text-ink-3">{humanize(t.term)}</dt>
                          <dd>{formatValue(t.value)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    EMPTY
                  )}
                </td>
                <td className={cx(tdNum, "min-w-40")}>
                  <span className="block">Peak falls by {formatMoney(r.peak_shortfall_reduction, currency)}</span>
                  <span className="mt-0.5 block text-xs font-normal text-ink-3">
                    {r.removes_shortfall
                      ? "Relaxing it removes the shortfall"
                      : `Shortfall remains without it (${r.first_shortfall_month_without_rule === null ? "none in horizon" : `month ${r.first_shortfall_month_without_rule}`})`}
                  </span>
                </td>
                <td className={cx(td, "min-w-40")}>
                  <Badge tone={backed ? "success" : "warning"} title="What this rule is based on">
                    {backed ? "Approved clause" : "Default assumption"}
                  </Badge>
                  <span className="mt-1 block text-xs text-ink-3">{r.basis}</span>
                </td>
                <td className={cx(td, "min-w-72")}>
                  {r.evidence.length === 0 ? (
                    <span className="text-xs text-ink-3">No approved clause; a default modelling value was used.</span>
                  ) : (
                    <div className="space-y-3">
                      <Citation ev={r.evidence[0]} version={byId.get(r.evidence[0].id)} householdId={householdId} />
                      {r.evidence.length > 1 && (
                        <details className="text-xs">
                          <summary className="cursor-pointer font-medium text-accent-ink">
                            {r.evidence.length - 1} more citation{r.evidence.length > 2 ? "s" : ""}
                          </summary>
                          <div className="mt-2 space-y-3">
                            {r.evidence.slice(1).map((ev) => (
                              <Citation key={`${ev.id}-${ev.revision}`} ev={ev} version={byId.get(ev.id)} householdId={householdId} />
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}
