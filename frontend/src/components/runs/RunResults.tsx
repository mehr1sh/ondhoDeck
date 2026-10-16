"use client";

import Link from "next/link";
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Badge,
  Button,
  Disclosure,
  LinkButton,
  PageHeader,
  Section,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { AssumptionSensitivity, formatValue, hasExplanation } from "./ExplanationPanel";
import { ContributingTerms } from "./ContributingTerms";
import { RunComparison } from "./RunComparison";
import {
  CHART,
  answerSentence,
  constraintVersions,
  hasShortfall,
  monthPhrase,
  shortfallRanges,
} from "./answer";
import { EMPTY, formatCell, formatDateTime, formatMoney, humanize, parseDecimal } from "@/lib/format";
import type { ModelName, MonthOut, RunDetail } from "@/lib/types";

export const SERIES_COLORS = { contract_aware: CHART.aware, naive: CHART.naive } as const;
export const MODEL_LABELS: Record<ModelName, string> = { contract_aware: "Contract-aware", naive: "Paper-wealth (naive)" };

export interface ChartPoint {
  month: number;
  label: string;
  contract_aware: number | null;
  naive: number | null;
}

/** Joins monthly rows of both models into one point per month (ending cash). */
export function buildChartData(months: MonthOut[]): ChartPoint[] {
  const byMonth = new Map<number, ChartPoint>();
  for (const m of months) {
    const p = byMonth.get(m.month) ?? { month: m.month, label: m.label, contract_aware: null, naive: null };
    const v = parseDecimal(m.ending_cash);
    if (m.model === "contract_aware") p.contract_aware = v;
    else if (m.model === "naive") p.naive = v;
    if (!p.label) p.label = m.label;
    byMonth.set(m.month, p);
  }
  return [...byMonth.values()].sort((a, b) => a.month - b.month);
}

const MONTH_COLUMNS: Array<{ key: keyof MonthOut; label: string }> = [
  { key: "beginning_cash", label: "Beginning cash" },
  { key: "income", label: "Income" },
  { key: "expenses", label: "Expenses" },
  { key: "taxes", label: "Taxes" },
  { key: "debt_service", label: "Debt service" },
  { key: "collateral_call", label: "Collateral call" },
  { key: "capital_call", label: "Capital call" },
  { key: "redemption_requested", label: "Redemption requested" },
  { key: "redemption_proceeds", label: "Redemption proceeds" },
  { key: "other_proceeds", label: "Other proceeds" },
  { key: "ending_cash", label: "Ending cash" },
  { key: "shortfall", label: "Shortfall" },
];

export const LIMITATIONS = [
  "Deterministic model: one path per scenario, with no probabilities attached to outcomes.",
  "Models one non-traded REIT allocation and one interval-fund allocation per household.",
  "Contract terms are resolved once, at the projection start date; later amendments or supersessions are not applied mid-horizon.",
  "Results depend on the scenario assumptions and the approved terms listed here. This is not investment, tax or legal advice.",
];

function AnswerBlock({ run }: { run: RunDetail }) {
  const ccy = run.reporting_currency;
  const aware = run.aware_summary;
  const naive = run.naive_summary;
  const short = hasShortfall(aware);
  const binding =
    hasExplanation(run.explanation) && short ? run.explanation.binding_in_first_shortfall_month : [];
  return (
    <section
      aria-labelledby="run-answer"
      className={cx("rounded-sm border border-line border-l-4 bg-surface px-5 py-5", short ? "border-l-risk" : "border-l-accent")}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Answer · contract-aware model</p>
      <p id="run-answer" className="font-display mt-1 text-[1.6rem] leading-snug text-ink" data-testid="run-answer">
        {answerSentence(run)}
      </p>
      <dl className="mt-4 grid gap-x-10 gap-y-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-ink-3">Peak deficit</dt>
          <dd className={cx("text-base font-semibold tabular-nums", short ? "text-risk" : "text-ink")}>
            {formatMoney(aware.peak_shortfall, ccy)}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Lowest month-end cash</dt>
          <dd className="text-base font-semibold tabular-nums text-ink">{formatMoney(aware.min_cash, ccy)}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Paper-wealth (naive) model</dt>
          <dd className="text-base font-semibold text-ink">
            {hasShortfall(naive)
              ? `Shortfall in ${monthPhrase(run, naive.first_shortfall_month as number)}`
              : "No shortfall in horizon"}
          </dd>
        </div>
      </dl>
      {binding.length > 0 && (
        <p className="mt-3 text-sm text-ink-2">
          <span className="text-ink-3">Binding in the first shortfall month:</span> {binding.join("; ")}
        </p>
      )}
      <Disclosure className="mt-4">
        Modelled projection — not a guaranteed outcome. {run.horizon_months}-month horizon, reported in {ccy}. The
        paper-wealth model assumes holdings can be sold at a fixed haircut; the contract-aware model applies the approved
        terms below.
      </Disclosure>
    </section>
  );
}

function CashChart({ run, data }: { run: RunDetail; data: ChartPoint[] }) {
  const [showTable, setShowTable] = useState(false);
  const ccy = run.reporting_currency;
  const ranges = shortfallRanges(run.months);
  return (
    <div className="space-y-3">
      <figure aria-label="Month-end cash for the contract-aware and paper-wealth models">
        <div className="h-72 w-full sm:h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 16, bottom: 8, left: 8 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              {ranges.map(([a, b]) => (
                <ReferenceArea
                  key={`${a}-${b}`}
                  x1={a === b ? a - 0.4 : a}
                  x2={a === b ? b + 0.4 : b}
                  fill={CHART.shortfallFill}
                  fillOpacity={0.9}
                  stroke="none"
                  ifOverflow="extendDomain"
                  label={{ value: "Shortfall", position: "insideTop", fontSize: 11, fill: CHART.shortfallStroke }}
                />
              ))}
              <XAxis
                dataKey="month"
                type="number"
                domain={["dataMin", "dataMax"]}
                allowDecimals={false}
                tick={{ fontSize: 12, fill: CHART.axis }}
                stroke={CHART.rule}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 12, fill: CHART.axis }}
                stroke={CHART.rule}
                tickLine={false}
                width={72}
                tickFormatter={(v: number) => formatMoney(v, ccy, { compact: true })}
              />
              <Tooltip
                formatter={(value: number | string, name: string) => [formatMoney(value, ccy), name]}
                labelFormatter={(m: number) => {
                  const p = data.find((d) => d.month === m);
                  return p?.label ? `Month ${m} · ${p.label}` : `Month ${m}`;
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: CHART.axis }} />
              <ReferenceLine
                y={0}
                stroke={CHART.zero}
                strokeWidth={1}
                label={{ value: "Zero cash", position: "insideTopRight", fontSize: 11, fill: CHART.axis }}
              />
              <Line
                type="linear"
                dataKey="contract_aware"
                name={MODEL_LABELS.contract_aware}
                stroke={SERIES_COLORS.contract_aware}
                strokeWidth={2.25}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                type="linear"
                dataKey="naive"
                name={MODEL_LABELS.naive}
                stroke={SERIES_COLORS.naive}
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <figcaption className="small-print mt-2">
          Month-end cash. Contract-aware (solid) applies the approved contract terms; paper-wealth (dashed) assumes
          holdings can be sold at a fixed haircut. Shaded months are contract-aware shortfall months; below the zero line
          cash is negative.
        </figcaption>
      </figure>
      <Button variant="secondary" size="sm" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
        {showTable ? "Hide chart data table" : "Show chart data table"}
      </Button>
      {showTable && (
        <TableWrap label="Chart data: month-end cash">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={th}>Month</th>
                <th className={thNum}>{MODEL_LABELS.contract_aware}</th>
                <th className={thNum}>{MODEL_LABELS.naive}</th>
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {data.map((p) => (
                <tr key={p.month}>
                  <td className={td}>
                    {p.month} <span className="text-xs text-ink-3">{p.label}</span>
                  </td>
                  <td className={tdNum}>{formatMoney(p.contract_aware, ccy)}</td>
                  <td className={tdNum}>{formatMoney(p.naive, ccy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}

function TermsUsedTable({ run }: { run: RunDetail }) {
  return (
    <TableWrap label="Terms used">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={th}>Term</th>
            <th className={thNum}>Value</th>
            <th className={th}>Provenance</th>
            <th className={th}>Source</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {run.terms.map((t) => (
            <tr key={t.term} className={t.source_backed ? undefined : "bg-caution-subtle/50"}>
              <td className={td}>{humanize(t.term)}</td>
              <td className={tdNum}>{formatValue(t.value)}</td>
              <td className={td}>{t.provenance}</td>
              <td className={td}>
                {t.source_backed ? (
                  <Badge tone="success">Source-backed</Badge>
                ) : t.basis === "derived_from_clause" ? (
                  <Badge tone="info" title="A modelling interpretation of an approved clause, not a value the clause states">
                    Derived from clause
                  </Badge>
                ) : t.basis === "household_record" ? (
                  <Badge tone="neutral">Household record</Badge>
                ) : (
                  <Badge tone="warning" title="No approved source constraint; a default assumption was used">
                    Default assumption
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function InputsTable({ inputs, currency }: { inputs: Record<string, unknown>; currency: string }) {
  const entries = Object.entries(inputs).filter(([k]) => k !== "assumption_sources");
  if (!entries.length) return <p className="text-sm text-ink-3">No input snapshot was stored for this run.</p>;
  const sources =
    inputs.assumption_sources && typeof inputs.assumption_sources === "object"
      ? (inputs.assumption_sources as Record<string, string>)
      : {};
  return (
    <TableWrap label="Assumptions used">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={th}>Assumption</th>
            <th className={thNum}>Value</th>
            <th className={th}>Source</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className={td}>{humanize(k)}</td>
              <td className={tdNum}>
                {typeof v === "number" && /^(lever_reserve_prefund|lever_sbl_paydown|lever_rsu_window_presale|lever_discretionary_cut|lever_reit_prestress_request)$/.test(k)
                  ? formatMoney(v, currency)
                  : formatValue(v)}
              </td>
              <td className={cx(td, "text-xs text-ink-3")}>{sources[k] ?? "Scenario assumption (unsourced)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function RunResults({ run, householdId }: { run: RunDetail; householdId: string }) {
  const [model, setModel] = useState<ModelName>("contract_aware");
  const ccy = run.reporting_currency;
  const chartData = buildChartData(run.months);
  const rows = run.months.filter((m) => m.model === model).sort((a, b) => a.month - b.month);
  const liq = run.liquidity ?? {};
  const scenarioBase = `/households/${householdId}/scenarios/${run.scenario_id}`;
  const defaults = run.terms.filter((t) => t.provenance.toLowerCase().startsWith("default"));
  const unbacked = run.terms.filter((t) => !t.source_backed).length;
  const explanation = hasExplanation(run.explanation) ? run.explanation : null;
  const versions = constraintVersions(run);
  const short = hasShortfall(run.aware_summary);

  return (
    <div className="space-y-10">
      <PageHeader
        level={2}
        eyebrow={
          <>
            <Link href={scenarioBase} className="underline-offset-2 hover:text-ink hover:underline">
              Scenario: {run.scenario_name || "Scenario"}
            </Link>{" "}
            ·{" "}
            <Link href={`/households/${householdId}/history`} className="underline-offset-2 hover:text-ink hover:underline">
              Run history
            </Link>
          </>
        }
        title="Liquidity analysis"
        description={`Run ${formatDateTime(run.created_at)} · ${run.horizon_months}-month horizon · engine ${run.engine_version} · reported in ${ccy}`}
        actions={
          <>
            <LinkButton href={`/households/${householdId}/exports?run_id=${run.id}`} variant="primary">
              Create report
            </LinkButton>
            <LinkButton href={`${scenarioBase}/prevention`}>Prevention planner</LinkButton>
            <LinkButton href={scenarioBase}>Edit scenario</LinkButton>
          </>
        }
      />

      <AnswerBlock run={run} />

      <Section title="Monthly cash" description="Month-end cash under both models, with contract-aware shortfall months marked.">
        {chartData.length ? (
          <CashChart run={run} data={chartData} />
        ) : (
          <p className="text-sm text-ink-3">This run has no monthly rows.</p>
        )}
      </Section>

      <Section
        title="Contributing terms"
        description="Contract rules that drive the result. Contribution is how much the peak shortfall falls when the rule is relaxed and the same model is re-run."
      >
        {!explanation ? (
          <p className="text-sm text-ink-3">
            No explanation is stored for this run (it was created before explanations were available). Run the scenario
            again to see contributing terms with citations.
          </p>
        ) : !short ? (
          <p className="text-sm text-ink-3">There is no shortfall to attribute. The terms applied are listed below.</p>
        ) : explanation.contributing_rules.length === 0 ? (
          <p className="text-sm text-ink-3">
            Relaxing individual contract rules does not change the shortfall; it is driven by the cash-flow inputs.
          </p>
        ) : (
          <ContributingTerms
            rules={explanation.contributing_rules}
            versions={versions}
            householdId={householdId}
            currency={ccy}
          />
        )}
        <details className="group">
          <summary className="cursor-pointer select-none text-sm font-medium text-accent-ink underline-offset-2 hover:underline">
            All terms applied in this run ({run.terms.length})
          </summary>
          <div className="mt-3 space-y-2">
            {unbacked > 0 && (
              <p className="text-sm text-caution">
                {unbacked} term{unbacked === 1 ? " was" : "s were"} not backed by an approved source constraint and used a
                default assumption. Review and approve terms to replace them.
              </p>
            )}
            {run.terms.length ? <TermsUsedTable run={run} /> : <p className="text-sm text-ink-3">No terms recorded.</p>}
          </div>
        </details>
      </Section>

      <Section
        title="Scenario comparison"
        description="Compare this run (baseline) with another run of the same household. All values come from each stored run."
        action={
          <>
            <Link href={scenarioBase} className="text-accent-ink underline-offset-2 hover:underline">
              Blind-spot check
            </Link>
            <span aria-hidden="true" className="text-ink-3">
              ·
            </span>
            <Link href={`${scenarioBase}/stress`} className="text-accent-ink underline-offset-2 hover:underline">
              Reverse stress test
            </Link>
            <span aria-hidden="true" className="text-ink-3">
              ·
            </span>
            <Link href={`${scenarioBase}/prevention`} className="text-accent-ink underline-offset-2 hover:underline">
              Prevention planner
            </Link>
          </>
        }
      >
        <RunComparison run={run} householdId={householdId} />
      </Section>

      <Section title="Assumptions and limitations">
        <div className="space-y-6">
          {run.warnings.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-ink">Warnings ({run.warnings.length})</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-caution">
                {run.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <h3 className="text-sm font-semibold text-ink">Defaults used</h3>
            {defaults.length === 0 ? (
              <p className="mt-1 text-sm text-ink-3">No term fell back to a default modelling value.</p>
            ) : (
              <ul className="mt-1 space-y-0.5 text-sm text-ink-2">
                {defaults.map((t) => (
                  <li key={t.term}>
                    <span className="font-medium">{humanize(t.term)}</span>:{" "}
                    <span className="tabular-nums">{formatValue(t.value)}</span>{" "}
                    <span className="text-ink-3">({t.provenance})</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-ink">Scenario assumptions used</h3>
            <InputsTable inputs={run.inputs_snapshot ?? {}} currency={ccy} />
          </div>
          {explanation && explanation.material_assumptions.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">Sensitivity of key assumptions</h3>
              <AssumptionSensitivity assumptions={explanation.material_assumptions} currency={ccy} />
            </div>
          )}
          {explanation?.excluded_unsupported && explanation.excluded_unsupported.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-ink">Approved terms not used: evidence does not support them</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-risk">
                {explanation.excluded_unsupported.map((x) => (
                  <li key={x.constraint_id}>
                    {humanize(x.type)} · {x.document} PDF page {x.pdf_page} ({x.reasons.map(humanize).join(", ")})
                  </li>
                ))}
              </ul>
            </div>
          )}
          {explanation?.not_modelled && explanation.not_modelled.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-ink">Approved terms not modelled numerically</h3>
              <p className="mt-0.5 text-xs text-ink-3">
                These restrictions apply to the holdings but the engine gives them no numerical effect; they are risks to
                weigh, not causes of the result above.
              </p>
              <ul className="mt-1 space-y-1.5 text-sm text-ink-2">
                {explanation.not_modelled.map((e) => (
                  <li key={e.id}>
                    <span className="font-medium">{humanize(e.type)}</span> · {e.document} PDF page {e.pdf_page}
                    <span className="block text-xs text-ink-3">{e.reason}</span>
                    {e.quote && <span className="evidence-quote block line-clamp-2 text-xs">“{e.quote}”</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <h3 className="text-sm font-semibold text-ink">Limitations</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {LIMITATIONS.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
          {explanation?.method && (
            <details className="small-print">
              <summary className="cursor-pointer select-none">How the contributing terms are computed</summary>
              <p className="mt-1 whitespace-pre-wrap">{explanation.method}</p>
            </details>
          )}
        </div>
      </Section>

      {Object.keys(liq).length > 0 && (
        <Section title="Liquidity available under stress">
          <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(liq).map(([k, v]) => (
              <div key={k}>
                <dt className="text-ink-3">{humanize(k)}</dt>
                <dd className="tabular-nums text-ink">{formatCell(k, v, ccy)}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      <Section
        title="Monthly cash-flow detail"
        action={
          <div role="group" aria-label="Model" className="inline-flex rounded-sm border border-line-strong p-0.5">
            {(["contract_aware", "naive"] as ModelName[]).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={model === m}
                onClick={() => setModel(m)}
                className={cx(
                  "rounded-sm px-3 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-accent",
                  model === m ? "bg-ink text-white" : "text-ink-2 hover:bg-surface-muted",
                )}
              >
                {MODEL_LABELS[m]}
              </button>
            ))}
          </div>
        }
      >
        <TableWrap label={`Monthly cash flow, ${MODEL_LABELS[model]} model`}>
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={th}>Month</th>
                {MONTH_COLUMNS.map((c) => (
                  <th key={c.key} className={thNum}>
                    {c.label}
                  </th>
                ))}
                <th className={th}>Binding constraints</th>
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {rows.map((r) => {
                const rowShort = (parseDecimal(r.shortfall) ?? 0) > 0;
                return (
                  <tr key={`${r.model}-${r.month}`} className={rowShort ? "bg-risk-subtle" : undefined}>
                    <td className={cx(td, "whitespace-nowrap")}>
                      {r.month} <span className="text-xs text-ink-3">{r.label}</span>
                      {rowShort && <span className="sr-only"> (shortfall)</span>}
                    </td>
                    {MONTH_COLUMNS.map((c) => (
                      <td key={c.key} className={cx(tdNum, c.key === "shortfall" && rowShort && "font-semibold text-risk")}>
                        {formatMoney(r[c.key], ccy)}
                      </td>
                    ))}
                    <td className={cx(td, "min-w-48 text-xs")}>
                      {r.binding_constraints.length ? r.binding_constraints.join("; ") : EMPTY}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      </Section>
    </div>
  );
}
