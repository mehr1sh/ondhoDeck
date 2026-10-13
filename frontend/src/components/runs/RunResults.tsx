"use client";

import Link from "next/link";
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Badge,
  Card,
  LinkButton,
  Notice,
  Stat,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { EMPTY, formatCell, formatDateTime, formatMoney, humanize, parseDecimal } from "@/lib/format";
import type { ModelName, MonthOut, RunDetail } from "@/lib/types";

export const SERIES_COLORS = { contract_aware: "#2563eb", naive: "#d97706" } as const;
export const MODEL_LABELS: Record<ModelName, string> = { contract_aware: "Contract-aware", naive: "Naive" };

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

function shortfallValue(summary: RunDetail["aware_summary"], currency: string) {
  const month = summary.first_shortfall_month;
  if (month === null || month === undefined) return { value: "None in horizon", tone: "success" as const };
  return {
    value: `Month ${month} · ${formatMoney(summary.shortfall_amount, currency)}`,
    tone: "danger" as const,
  };
}

function CashChart({ data, currency }: { data: ChartPoint[]; currency: string }) {
  return (
    <figure aria-label="Ending cash by month for the contract-aware and naive models">
      <div className="h-72 w-full sm:h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#475569" }} stroke="#cbd5e1" tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "#475569" }}
              stroke="#cbd5e1"
              tickLine={false}
              width={72}
              tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
            />
            <Tooltip
              formatter={(value: number | string, name: string) => [formatMoney(value, currency), name]}
              labelFormatter={(m: number) => {
                const p = data.find((d) => d.month === m);
                return p?.label ? `Month ${m} (${p.label})` : `Month ${m}`;
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: "#334155" }} />
            <ReferenceLine y={0} stroke="#64748b" strokeWidth={1.5} label={{ value: "Zero cash", position: "insideTopRight", fontSize: 11, fill: "#475569" }} />
            <Line
              type="monotone"
              dataKey="contract_aware"
              name={MODEL_LABELS.contract_aware}
              stroke={SERIES_COLORS.contract_aware}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
              connectNulls
            />
            <Line
              type="monotone"
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
      <figcaption className="mt-2 text-xs text-slate-600">
        Ending cash each month. Contract-aware (solid) applies extracted contract terms; naive (dashed) assumes assets can
        be sold at a fixed haircut. Below the zero line is a shortfall. The monthly table below lists the same values.
      </figcaption>
    </figure>
  );
}

export function RunResults({ run, householdId }: { run: RunDetail; householdId: string }) {
  const [model, setModel] = useState<ModelName>("contract_aware");
  const ccy = run.reporting_currency;
  const chartData = buildChartData(run.months);
  const rows = run.months.filter((m) => m.model === model).sort((a, b) => a.month - b.month);
  const aware = shortfallValue(run.aware_summary, ccy);
  const naive = shortfallValue(run.naive_summary, ccy);
  const liq = run.liquidity ?? {};
  const liqWindow = typeof liq.window_months === "number" ? liq.window_months : null;
  const scenarioBase = `/households/${householdId}/scenarios/${run.scenario_id}`;
  const defaultTerms = run.terms.filter((t) => !t.source_backed).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href={`/households/${householdId}/history`} className="text-xs text-slate-600 hover:underline">
            ← History
          </Link>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">
            Run results{run.scenario_name ? `: ${run.scenario_name}` : ""}
          </h2>
          <p className="text-xs text-slate-600">
            {formatDateTime(run.created_at)} · {run.horizon_months}-month horizon · engine {run.engine_version} · reported
            in {ccy}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton size="sm" href={scenarioBase}>
            Edit scenario
          </LinkButton>
          <LinkButton size="sm" href={`${scenarioBase}/stress`}>
            Reverse stress
          </LinkButton>
          <LinkButton size="sm" href={`${scenarioBase}/prevention`}>
            Prevention planner
          </LinkButton>
          <LinkButton size="sm" href={`/households/${householdId}/exports?run_id=${run.id}`}>
            Export
          </LinkButton>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="First shortfall · contract-aware" value={aware.value} tone={aware.tone} />
        <Stat label="First shortfall · naive" value={naive.value} tone={naive.tone} />
        <Stat
          label="Minimum cash"
          value={formatMoney(run.aware_summary.min_cash, ccy)}
          hint={`Contract-aware. Naive: ${formatMoney(run.naive_summary.min_cash, ccy)}`}
          tone={(parseDecimal(run.aware_summary.min_cash) ?? 0) < 0 ? "danger" : undefined}
        />
        <Stat
          label={`Stress-usable liquidity${liqWindow ? ` (${liqWindow} mo)` : ""}`}
          value={formatMoney(liq.total, ccy)}
          hint={liq.naive_total !== undefined ? `Naive estimate: ${formatMoney(liq.naive_total, ccy)}` : undefined}
        />
      </div>

      {run.warnings.length > 0 && (
        <Notice tone="warning" title={`Warnings (${run.warnings.length})`}>
          <ul className="list-disc space-y-1 pl-5">
            {run.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Notice>
      )}

      <Card title="Ending cash by month">
        {chartData.length ? <CashChart data={chartData} currency={ccy} /> : <p className="text-sm text-slate-600">No monthly rows.</p>}
      </Card>

      <Card
        title="Monthly cash flow"
        actions={
          <div role="group" aria-label="Model" className="inline-flex rounded-md border border-slate-300 p-0.5">
            {(["contract_aware", "naive"] as ModelName[]).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={model === m}
                onClick={() => setModel(m)}
                className={cx(
                  "rounded px-3 py-1 text-xs font-medium",
                  model === m ? "bg-slate-800 text-white" : "text-slate-700 hover:bg-slate-100",
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
                const short = (parseDecimal(r.shortfall) ?? 0) > 0;
                return (
                  <tr key={`${r.model}-${r.month}`} className={short ? "bg-red-50" : undefined}>
                    <td className={cx(td, "whitespace-nowrap")}>
                      {r.month} <span className="text-xs text-slate-500">{r.label}</span>
                    </td>
                    {MONTH_COLUMNS.map((c) => (
                      <td key={c.key} className={cx(tdNum, c.key === "shortfall" && short && "font-semibold text-red-700")}>
                        {formatMoney(r[c.key], ccy)}
                      </td>
                    ))}
                    <td className={cx(td, "min-w-48 text-xs")}>{r.binding_constraints.length ? r.binding_constraints.join("; ") : EMPTY}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      </Card>

      {Object.keys(liq).length > 0 && (
        <Card title="Stress-usable liquidity breakdown">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(liq).map(([k, v]) => (
              <div key={k}>
                <dt className="text-slate-600">{humanize(k)}</dt>
                <dd className="tabular-nums text-slate-900">{formatCell(k, v, ccy)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}

      <Card title="Terms used">
        {defaultTerms > 0 && (
          <div className="mb-3">
            <Notice tone="warning">
              {defaultTerms} term{defaultTerms === 1 ? " was" : "s were"} not backed by an approved source constraint and
              used a default assumption. Review and approve constraints to replace them.
            </Notice>
          </div>
        )}
        {run.terms.length === 0 ? (
          <p className="text-sm text-slate-600">No terms recorded.</p>
        ) : (
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
                  <tr key={t.term} className={t.source_backed ? undefined : "bg-amber-50/60"}>
                    <td className={td}>{humanize(t.term)}</td>
                    <td className={tdNum}>
                      {typeof t.value === "number" || typeof t.value === "string" || typeof t.value === "boolean"
                        ? String(t.value)
                        : JSON.stringify(t.value)}
                    </td>
                    <td className={td}>{t.provenance}</td>
                    <td className={td}>
                      {t.source_backed ? (
                        <Badge tone="success">Source-backed</Badge>
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
        )}
      </Card>
    </div>
  );
}
