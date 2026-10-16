"use client";

import { Badge, Card, Notice, TableWrap, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { EMPTY, formatMoney, humanize } from "@/lib/format";
import type { ContributingRule, MaterialAssumption, RunDetail, RunExplanation } from "@/lib/types";

/** True when the run carries a (non-empty) explanation. Old runs have null or {}. */
export function hasExplanation(e: RunDetail["explanation"]): e is RunExplanation {
  return Boolean(e && typeof e === "object" && Array.isArray((e as RunExplanation).contributing_rules));
}

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return EMPTY;
  if (typeof v === "number" || typeof v === "string" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function monthLabel(m: number | null | undefined): string {
  return m === null || m === undefined ? "none in horizon" : `month ${m}`;
}

function RuleItem({ rule, currency }: { rule: ContributingRule; currency: string }) {
  const contractBacked = rule.evidence.length > 0;
  return (
    <li className="rounded-md border border-slate-200 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-900">{rule.rule}</span>
        {rule.removes_shortfall ? (
          <Badge tone="success">Removing it removes the shortfall</Badge>
        ) : (
          <Badge tone="neutral">
            Shortfall remains without it ({monthLabel(rule.first_shortfall_month_without_rule)})
          </Badge>
        )}
        <Badge tone={contractBacked ? "success" : "warning"} title="What this rule is based on">
          Basis: {rule.basis}
        </Badge>
      </div>
      <p className="mt-1 text-slate-700">
        Without this rule the peak shortfall falls by{" "}
        <strong className="tabular-nums">{formatMoney(rule.peak_shortfall_reduction, currency)}</strong>.
      </p>
      {rule.terms.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
          {rule.terms.map((t) => (
            <li key={t.term}>
              <span className="text-slate-600">{humanize(t.term)}:</span>{" "}
              <code className="tabular-nums">{formatValue(t.value)}</code> · {t.provenance}
            </li>
          ))}
        </ul>
      )}
      {rule.evidence.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Evidence (approved clauses)</p>
          {rule.evidence.map((ev) => (
            <figure key={`${ev.id}-${ev.revision}`} className="space-y-1">
              <blockquote className="evidence-quote border-l-2 border-accent bg-surface-muted px-4 py-2">
                “{ev.quote}”
              </blockquote>
              <figcaption className="text-xs text-slate-600">
                {ev.document || "Document"} · PDF page {ev.pdf_page} · {humanize(ev.type)}
                {ev.value !== null && ev.value !== undefined ? ` · value ${formatValue(ev.value)}` : ""} · revision{" "}
                {ev.revision}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </li>
  );
}

export function ExplanationPanel({ explanation, currency }: { explanation: RunExplanation; currency: string }) {
  const e = explanation;
  const shortfall = e.first_shortfall_month !== null && e.first_shortfall_month !== undefined;
  return (
    <Card title="Why this result">
      <div className="space-y-4">
        <Notice title="Counterfactual analysis of the deterministic model">
          Each contract rule is relaxed one at a time and the same simulation is re-run, and key assumptions are nudged up
          and down. This explains how the model reached its result. It is not advice or a forecast.
        </Notice>

        {shortfall ? (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-600">First shortfall</dt>
              <dd className="font-semibold text-red-700">Month {e.first_shortfall_month}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Shortfall in that month</dt>
              <dd className="tabular-nums">{formatMoney(e.shortfall_amount, currency)}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Peak shortfall</dt>
              <dd className="tabular-nums">{formatMoney(e.peak_shortfall, currency)}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-slate-700">The contract-aware model shows no shortfall within the horizon.</p>
        )}

        {shortfall && (
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Binding constraints in the first shortfall month</h3>
            {e.binding_in_first_shortfall_month.length ? (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-800">
                {e.binding_in_first_shortfall_month.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-slate-600">None recorded.</p>
            )}
          </div>
        )}

        {shortfall && (
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Contributing rules</h3>
            {e.contributing_rules.length ? (
              <ol className="mt-2 space-y-3">
                {e.contributing_rules.map((r) => (
                  <RuleItem key={r.relaxation} rule={r} currency={currency} />
                ))}
              </ol>
            ) : (
              <p className="mt-1 text-sm text-slate-600">
                Relaxing individual contract rules does not change the shortfall; it is driven by the cash-flow inputs.
              </p>
            )}
          </div>
        )}

        {e.material_assumptions.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Assumption sensitivity</h3>
            <AssumptionSensitivity assumptions={e.material_assumptions} currency={currency} />
          </div>
        )}

        {e.method && (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer select-none">How this explanation is computed</summary>
            <p className="mt-1 whitespace-pre-wrap">{e.method}</p>
          </details>
        )}
      </div>
    </Card>
  );
}

/** How the first shortfall and peak change when each key assumption is nudged down and up (from the API). */
export function AssumptionSensitivity({ assumptions, currency }: { assumptions: MaterialAssumption[]; currency: string }) {
  return (
    <>
      <TableWrap label="Assumption sensitivity">
        <table className={tableClass}>
          <thead>
            <tr>
              <th className={th}>Assumption</th>
              <th className={thNum}>Base value</th>
              <th className={th}>Variant</th>
              <th className={th}>First shortfall</th>
              <th className={thNum}>Peak shortfall</th>
              <th className={th}>Material</th>
            </tr>
          </thead>
          <tbody className={tbodyClass}>
            {assumptions.flatMap((a) =>
              a.variants.map((v, i) => (
                <tr key={`${a.assumption}-${v.direction}`} className={v.material ? "bg-caution-subtle/60" : undefined}>
                  {i === 0 && (
                    <>
                      <td className={td} rowSpan={a.variants.length}>
                        {a.label}
                        {a.material && (
                          <span className="ml-1">
                            <Badge tone="warning">Material</Badge>
                          </span>
                        )}
                      </td>
                      <td className={tdNum} rowSpan={a.variants.length}>
                        {formatValue(a.base_value)}
                      </td>
                    </>
                  )}
                  <td className={td}>
                    {humanize(v.direction)}: <span className="tabular-nums">{formatValue(v.value)}</span>
                  </td>
                  <td className={td}>{v.first_shortfall_month === null ? "None" : `Month ${v.first_shortfall_month}`}</td>
                  <td className={tdNum}>{formatMoney(v.peak_shortfall, currency)}</td>
                  <td className={td}>{v.material ? "Yes" : "No"}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </TableWrap>
      <p className="small-print mt-1">
        A variant is material when it changes whether a shortfall occurs, its first month, or the peak shortfall by more
        than 10%.
      </p>
    </>
  );
}
