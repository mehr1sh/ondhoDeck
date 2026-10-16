"use client";

import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  ErrorState,
  FilterSelect,
  LoadingBlock,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, parseDecimal } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import type { RunDetail } from "@/lib/types";
import { CHART, hasShortfall } from "./answer";

interface ComparePoint {
  month: number;
  baseline: number | null;
  alternative: number | null;
}

/** Aligns the contract-aware ending cash of two runs by projection month (values from the API). */
export function buildComparisonData(a: RunDetail, b: RunDetail): ComparePoint[] {
  const map = new Map<number, ComparePoint>();
  const add = (run: RunDetail, key: "baseline" | "alternative") => {
    for (const m of run.months) {
      if (m.model !== "contract_aware") continue;
      const p = map.get(m.month) ?? { month: m.month, baseline: null, alternative: null };
      p[key] = parseDecimal(m.ending_cash);
      map.set(m.month, p);
    }
  };
  add(a, "baseline");
  add(b, "alternative");
  return [...map.values()].sort((x, y) => x.month - y.month);
}

function firstShortfall(run: RunDetail): string {
  return hasShortfall(run.aware_summary) ? `Month ${run.aware_summary.first_shortfall_month}` : "None in horizon";
}

export function RunComparison({ run, householdId }: { run: RunDetail; householdId: string }) {
  const runs = useApiQuery(() => endpoints.listRuns(householdId, { limit: 50 }), [householdId]);
  const [otherId, setOtherId] = useState("");
  const other = useApiQuery(() => endpoints.getRun(otherId), [otherId], Boolean(otherId));
  const options = (runs.data?.items ?? []).filter((r) => r.id !== run.id);
  const alt = otherId && other.data?.id === otherId ? other.data : null;
  const ccy = run.reporting_currency;
  const sameCurrency = !alt || alt.reporting_currency === ccy;

  const rows: Array<{ label: string; base: string; alt: (r: RunDetail) => string; num?: boolean }> = [
    { label: "Scenario", base: run.scenario_name || EMPTY, alt: (r) => r.scenario_name || EMPTY },
    { label: "Run", base: formatDateTime(run.created_at), alt: (r) => formatDateTime(r.created_at) },
    { label: "Horizon", base: `${run.horizon_months} months`, alt: (r) => `${r.horizon_months} months` },
    { label: "First shortfall", base: firstShortfall(run), alt: firstShortfall },
    {
      label: "Shortfall in that month",
      base: formatMoney(run.aware_summary.shortfall_amount, ccy),
      alt: (r) => formatMoney(r.aware_summary.shortfall_amount, r.reporting_currency),
      num: true,
    },
    {
      label: "Peak shortfall",
      base: formatMoney(run.aware_summary.peak_shortfall, ccy),
      alt: (r) => formatMoney(r.aware_summary.peak_shortfall, r.reporting_currency),
      num: true,
    },
    {
      label: "Lowest month-end cash",
      base: formatMoney(run.aware_summary.min_cash, ccy),
      alt: (r) => formatMoney(r.aware_summary.min_cash, r.reporting_currency),
      num: true,
    },
  ];

  return (
    <div className="space-y-4">
      {runs.loading && !runs.data ? (
        <LoadingBlock rows={1} label="Loading other runs…" />
      ) : runs.error ? (
        <ErrorState error={runs.error} onRetry={() => void runs.reload()} />
      ) : options.length === 0 ? (
        <p className="text-sm text-ink-3">
          This household has no other runs to compare with.{" "}
          <Link href={`/households/${householdId}/scenarios`} className="text-accent-ink underline">
            Create or run another scenario
          </Link>{" "}
          to compare alternatives.
        </p>
      ) : (
        <div className="max-w-md">
          <FilterSelect
            label="Compare with"
            value={otherId}
            onChange={setOtherId}
            options={[
              { value: "", label: "Choose another run of this household" },
              ...options.map((r) => ({
                value: r.id,
                label: `${r.scenario_name || "Scenario"} · ${formatDateTime(r.created_at)}`,
              })),
            ]}
          />
        </div>
      )}

      {otherId && other.loading && !alt && <LoadingBlock rows={2} label="Loading comparison run…" />}
      {otherId && other.error ? <ErrorState error={other.error} onRetry={() => void other.reload()} /> : null}

      {alt && (
        <>
          {!sameCurrency && (
            <p className="text-sm text-caution">
              The runs report in different currencies ({ccy} and {alt.reporting_currency}); values are shown in each
              run&apos;s own currency and the chart is not comparable.
            </p>
          )}
          <TableWrap label="Run comparison">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Contract-aware result</th>
                  <th className={thNum}>This run (baseline)</th>
                  <th className={thNum}>Alternative</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <th scope="row" className={cx(td, "text-left font-medium text-ink-2")}>
                      {r.label}
                    </th>
                    <td className={tdNum}>{r.base}</td>
                    <td className={tdNum}>{r.alt(alt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          {sameCurrency && (
            <figure aria-label="Contract-aware ending cash by month: this run and the alternative">
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={buildComparisonData(run, alt)} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                    <CartesianGrid stroke={CHART.grid} vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.rule} tickLine={false} />
                    <YAxis
                      tick={{ fontSize: 12, fill: CHART.axis }}
                      stroke={CHART.rule}
                      tickLine={false}
                      width={72}
                      tickFormatter={(v: number) => formatMoney(v, ccy, { compact: true })}
                    />
                    <Tooltip
                      formatter={(value: number | string, name: string) => [formatMoney(value, ccy), name]}
                      labelFormatter={(m: number) => `Month ${m}`}
                    />
                    <Legend wrapperStyle={{ fontSize: 12, color: CHART.axis }} />
                    <ReferenceLine y={0} stroke={CHART.zero} strokeWidth={1} />
                    <Line
                      type="linear"
                      dataKey="baseline"
                      name="This run"
                      stroke={CHART.aware}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />
                    <Line
                      type="linear"
                      dataKey="alternative"
                      name={`Alternative: ${alt.scenario_name || "run"}`}
                      stroke={CHART.alt}
                      strokeWidth={2}
                      strokeDasharray="2 3"
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <figcaption className="small-print mt-1">
                Contract-aware ending cash for both runs, as returned by each run. Solid: this run. Dotted: alternative.
              </figcaption>
            </figure>
          )}
        </>
      )}
    </div>
  );
}
