"use client";

import Link from "next/link";
import { Card, ErrorState, LinkButton, LoadingBlock, Stat, TableWrap, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { useHousehold } from "@/components/household/HouseholdContext";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, humanize } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

function ByCurrencyTable({ title, data }: { title: string; data: Record<string, Record<string, string>> }) {
  const rows = Object.entries(data).flatMap(([kind, byCcy]) =>
    Object.entries(byCcy).map(([ccy, amount]) => ({ kind, ccy, amount })),
  );
  return (
    <Card title={title}>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-600">None recorded.</p>
      ) : (
        <TableWrap label={title}>
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={th}>Kind</th>
                <th className={th}>Currency</th>
                <th className={thNum}>Amount</th>
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {rows.map((r) => (
                <tr key={`${r.kind}-${r.ccy}`}>
                  <td className={td}>{humanize(r.kind)}</td>
                  <td className={td}>{r.ccy}</td>
                  <td className={tdNum}>{formatMoney(r.amount, r.ccy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

function perCurrency(map: Record<string, string>): string {
  const entries = Object.entries(map);
  if (!entries.length) return EMPTY;
  return entries.map(([ccy, v]) => formatMoney(v, ccy)).join(" + ");
}

export default function HouseholdOverviewPage() {
  const { household } = useHousehold();
  const q = useApiQuery(() => endpoints.householdSummary(household.id), [household.id]);
  const base = `/households/${household.id}`;

  if (q.loading && !q.data) return <LoadingBlock rows={5} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const s = q.data;
  const run = s.latest_run;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Monthly income" value={perCurrency(s.monthly_income)} />
        <Stat label="Monthly expenses" value={perCurrency(s.monthly_expenses)} />
        <Stat
          label="Records"
          value={
            <span className="text-sm font-normal text-slate-700">
              {Object.entries(s.counts)
                .map(([k, v]) => `${v} ${humanize(k).toLowerCase()}`)
                .join(" · ") || EMPTY}
            </span>
          }
        />
        <Stat
          label="Latest run"
          value={
            run ? (
              <Link href={`${base}/runs/${run.id}`} className="text-base underline">
                {run.scenario_name || "View run"}
              </Link>
            ) : (
              "None yet"
            )
          }
          hint={run ? formatDateTime(run.created_at) : <Link href={`${base}/scenarios`} className="underline">Create a scenario and run it</Link>}
        />
      </div>
      {run && (
        <Card title="Latest run: first shortfall">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-slate-600">Contract-aware model</dt>
              <dd className="font-semibold tabular-nums">
                {run.aware_summary.first_shortfall_month == null
                  ? "No shortfall in horizon"
                  : `Month ${run.aware_summary.first_shortfall_month} · ${formatMoney(run.aware_summary.shortfall_amount, run.reporting_currency)}`}
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">Naive model</dt>
              <dd className="font-semibold tabular-nums">
                {run.naive_summary.first_shortfall_month == null
                  ? "No shortfall in horizon"
                  : `Month ${run.naive_summary.first_shortfall_month} · ${formatMoney(run.naive_summary.shortfall_amount, run.reporting_currency)}`}
              </dd>
            </div>
          </dl>
        </Card>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        <ByCurrencyTable title="Assets by kind" data={s.totals_by_kind} />
        <ByCurrencyTable title="Liabilities by kind" data={s.liabilities_by_kind} />
      </div>
      <div className="flex flex-wrap gap-2">
        <LinkButton href={`${base}/profile`}>Edit financial profile</LinkButton>
        <LinkButton href={`${base}/documents`}>Upload contracts</LinkButton>
        <LinkButton href={`${base}/constraints`}>Review constraints</LinkButton>
        <LinkButton href={`${base}/scenarios`} variant="primary">
          Scenarios
        </LinkButton>
      </div>
    </div>
  );
}
