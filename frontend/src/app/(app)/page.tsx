"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, SyntheticBadge } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { endpoints } from "@/lib/endpoints";
import { describeError, useApiQuery } from "@/lib/hooks";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { HouseholdOut, HouseholdSummary } from "@/lib/types";

interface Row {
  household: HouseholdOut;
  summary: HouseholdSummary | null;
  summaryError: unknown;
}

function ShortfallText({ month, amount, currency }: { month: unknown; amount: unknown; currency: string }) {
  if (month === null || month === undefined) return <span className="text-emerald-700">No shortfall</span>;
  return (
    <span className="text-red-700">
      Month {String(month)} · {formatMoney(amount, currency)}
    </span>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const toast = useToast();
  const [creatingDemo, setCreatingDemo] = useState(false);

  const q = useApiQuery(async (): Promise<{ rows: Row[]; total: number }> => {
    const page = await endpoints.listHouseholds({ limit: 50 });
    const summaries = await Promise.allSettled(page.items.map((h) => endpoints.householdSummary(h.id)));
    return {
      total: page.total,
      rows: page.items.map((h, i) => {
        const s = summaries[i]!;
        return {
          household: h,
          summary: s.status === "fulfilled" ? s.value : null,
          summaryError: s.status === "rejected" ? s.reason : null,
        };
      }),
    };
  }, []);

  const createDemo = async () => {
    setCreatingDemo(true);
    try {
      const h = await endpoints.createDemoHousehold();
      toast.success("Demo household created", "It contains synthetic data and synthetic sample contracts.");
      router.push(`/households/${h.id}`);
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setCreatingDemo(false);
    }
  };

  const actions = (
    <>
      <LinkButton href="/households/new" variant="primary">
        Create household
      </LinkButton>
      <Button variant="secondary" onClick={createDemo} loading={creatingDemo}>
        Create demo household (synthetic)
      </Button>
    </>
  );

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Contract-aware liquidity overview across your households."
        actions={q.data && q.data.rows.length > 0 ? actions : undefined}
      />
      {q.loading && !q.data ? (
        <LoadingBlock rows={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : !q.data || q.data.rows.length === 0 ? (
        <EmptyState title="No households yet" action={actions}>
          Create a household to record assets, obligations and contracts, or explore SlipSlopes with a demo household.
          The demo uses <strong>synthetic data and synthetic sample contracts</strong>, clearly labelled throughout.
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data.rows.map(({ household: h, summary, summaryError }) => {
            const run = summary?.latest_run ?? null;
            return (
              <article key={h.id} className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold text-slate-900">
                    <Link href={`/households/${h.id}`} className="hover:underline">
                      {h.name}
                    </Link>
                  </h2>
                  {h.is_demo && <SyntheticBadge />}
                  <Badge>{h.reporting_currency}</Badge>
                </div>
                <div className="mt-3 flex-1 text-sm">
                  {summaryError ? (
                    <p className="text-xs text-red-800">Summary unavailable: {describeError(summaryError).message}</p>
                  ) : run ? (
                    <dl className="space-y-1">
                      <div className="flex justify-between gap-2">
                        <dt className="text-slate-600">Latest run</dt>
                        <dd className="text-right">
                          <Link href={`/households/${h.id}/runs/${run.id}`} className="underline">
                            {run.scenario_name || "Run"}
                          </Link>
                          <span className="block text-xs text-slate-500">{formatDateTime(run.created_at)}</span>
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-slate-600">Contract-aware shortfall</dt>
                        <dd className="tabular-nums">
                          <ShortfallText month={run.aware_summary.first_shortfall_month} amount={run.aware_summary.shortfall_amount} currency={run.reporting_currency} />
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-slate-600">Naive shortfall</dt>
                        <dd className="tabular-nums">
                          <ShortfallText month={run.naive_summary.first_shortfall_month} amount={run.naive_summary.shortfall_amount} currency={run.reporting_currency} />
                        </dd>
                      </div>
                    </dl>
                  ) : (
                    <p className="text-slate-600">No simulation runs yet.</p>
                  )}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <LinkButton size="sm" href={`/households/${h.id}/profile`}>
                    Profile
                  </LinkButton>
                  <LinkButton size="sm" href={`/households/${h.id}/documents`}>
                    Documents
                  </LinkButton>
                  <LinkButton size="sm" href={`/households/${h.id}/scenarios`}>
                    Scenarios
                  </LinkButton>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {q.data && q.data.total > q.data.rows.length && (
        <p className="mt-4 text-sm text-slate-600">
          Showing {q.data.rows.length} of {q.data.total}.{" "}
          <Link href="/households" className="underline">
            View all households
          </Link>
        </p>
      )}
    </div>
  );
}
