"use client";

import Link from "next/link";
import {
  Card,
  ErrorState,
  LinkButton,
  LoadingBlock,
  Section,
  TableWrap,
  WorkflowProgress,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { useHousehold } from "@/components/household/HouseholdContext";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, humanize } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import { householdWorkflow } from "@/lib/workflow";

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
  const docs = useApiQuery(() => endpoints.listDocuments(household.id, { limit: 100 }), [household.id]);
  const plans = useApiQuery(() => endpoints.listPrevention(household.id, { limit: 1 }), [household.id]);
  const exportsQ = useApiQuery(() => endpoints.listExports(household.id, { limit: 1 }), [household.id]);
  const base = `/households/${household.id}`;

  if (q.loading && !q.data) return <LoadingBlock rows={5} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const s = q.data;
  const run = s.latest_run;
  const sideError = docs.error ?? plans.error ?? exportsQ.error;
  const sideReady = Boolean(docs.data && plans.data && exportsQ.data);
  const workflow = sideReady
    ? householdWorkflow({
        householdId: household.id,
        counts: s.counts,
        documents: docs.data!.items,
        latestRun: run,
        preventionPlans: plans.data!.total,
        exports: exportsQ.data!.total,
      })
    : null;

  return (
    <div className="space-y-8">
      <Section
        title="Workflow"
        description="Each step reflects this household's records. Select a step to open it."
        action={
          workflow?.next?.href ? (
            <LinkButton href={workflow.next.href} variant="primary" size="sm">
              Next step: {workflow.next.label}
            </LinkButton>
          ) : undefined
        }
      >
        {sideError ? (
          <ErrorState
            error={sideError}
            onRetry={() => {
              if (docs.error) void docs.reload();
              if (plans.error) void plans.reload();
              if (exportsQ.error) void exportsQ.reload();
            }}
          />
        ) : !workflow ? (
          <LoadingBlock rows={1} label="Loading workflow…" />
        ) : (
          <WorkflowProgress steps={workflow.steps} label="Household workflow" />
        )}
      </Section>

      <Section title="Latest analysis">
        {run ? (
          <div className="space-y-2">
            <p className="font-display text-lg text-ink">
              {run.aware_summary.first_shortfall_month == null
                ? `No projected shortfall over the ${run.horizon_months}-month horizon.`
                : `Projected shortfall of ${formatMoney(run.aware_summary.shortfall_amount, run.reporting_currency)} in month ${run.aware_summary.first_shortfall_month}.`}
            </p>
            <p className="text-sm text-ink-3">
              Contract-aware model ·{" "}
              <Link href={`${base}/scenarios/${run.scenario_id}`} className="underline-offset-2 hover:underline">
                {run.scenario_name || "Scenario"}
              </Link>{" "}
              · run {formatDateTime(run.created_at)}
            </p>
            <LinkButton href={`${base}/runs/${run.id}`} size="sm">
              Open analysis
            </LinkButton>
          </div>
        ) : (
          <p className="text-sm text-ink-3">
            No analysis yet.{" "}
            <Link href={`${base}/scenarios`} className="text-accent-ink underline">
              Create a liquidity scenario and run it
            </Link>
            .
          </p>
        )}
      </Section>

      <Section title="Monthly cash flow">
        <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-3">Monthly income</dt>
            <dd className="font-medium tabular-nums text-ink">{perCurrency(s.monthly_income)}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Monthly expenses</dt>
            <dd className="font-medium tabular-nums text-ink">{perCurrency(s.monthly_expenses)}</dd>
          </div>
        </dl>
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <ByCurrencyTable title="Assets by kind" data={s.totals_by_kind} />
        <ByCurrencyTable title="Liabilities by kind" data={s.liabilities_by_kind} />
      </div>
    </div>
  );
}
