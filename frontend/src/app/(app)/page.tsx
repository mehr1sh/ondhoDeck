"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import {
  Button,
  EmptyState,
  ErrorState,
  LinkButton,
  LoadingBlock,
  PageHeader,
  Section,
  SyntheticBadge,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { DocumentStatusBadge } from "@/components/badges";
import { useToast } from "@/components/Toast";
import { endpoints } from "@/lib/endpoints";
import { describeError, useApiQuery } from "@/lib/hooks";
import { EMPTY, formatDateTime, formatMoney, humanize } from "@/lib/format";
import {
  PROCESSING_STATUSES,
  deriveActions,
  docHref,
  projectedShortfalls,
  recentAnalyses,
  type OverviewAction,
} from "@/lib/overview";

const RECENT = 6;

function NextActionPanel({ actions, extra }: { actions: OverviewAction[]; extra?: ReactNode }) {
  const [next, ...rest] = actions;
  if (!next) return null;
  return (
    <section
      aria-labelledby="next-action-heading"
      className={cx(
        "rounded-sm border border-line border-l-4 bg-surface px-5 py-4",
        next.tone === "risk" ? "border-l-risk" : next.tone === "attention" ? "border-l-caution" : "border-l-accent",
      )}
    >
      <p id="next-action-heading" className="text-xs font-semibold uppercase tracking-wide text-ink-3">
        Next action
      </p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <p className="font-display text-xl leading-snug text-ink" data-testid="next-action-title">
            {next.title}
          </p>
          <p className="mt-1 text-sm text-ink-2">{next.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton href={next.href} variant="primary">
            {next.cta}
          </LinkButton>
          {extra}
        </div>
      </div>
      {rest.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-xs font-medium text-ink-3">Also outstanding</p>
          <ul className="mt-1 space-y-1 text-sm">
            {rest.map((a, i) => (
              <li key={`${a.kind}-${i}`}>
                <Link href={a.href} className="text-accent-ink underline-offset-2 hover:underline">
                  {a.title}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export default function OverviewPage() {
  const router = useRouter();
  const toast = useToast();
  const [creatingDemo, setCreatingDemo] = useState(false);

  const households = useApiQuery(() => endpoints.listHouseholds({ limit: 100 }), []);
  const review = useApiQuery(() => endpoints.reviewQueue(1), []);
  const scenarios = useApiQuery(() => endpoints.myScenarios(), []);
  const documents = useApiQuery(() => endpoints.myDocuments({ limit: 100 }), []);

  const currency = (hid: string) => households.data?.items.find((h) => h.id === hid)?.reporting_currency;

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

  const queries = [households, review, scenarios, documents];
  const firstError = queries.find((q) => q.error)?.error;
  const ready = Boolean(households.data && review.data && scenarios.data && documents.data);
  const actions = useMemo(
    () =>
      ready
        ? deriveActions({
            households: households.data!.items,
            review: review.data!,
            scenarios: scenarios.data!,
            documents: documents.data!.items,
          })
        : [],
    [ready, households.data, review.data, scenarios.data, documents.data],
  );

  const reloadAll = () => queries.forEach((q) => q.error && void q.reload());

  const headerActions = (
    <>
      <LinkButton href="/households/new" variant="primary">
        Create household
      </LinkButton>
      <Button variant="secondary" onClick={createDemo} loading={creatingDemo}>
        Create demo household
      </Button>
    </>
  );

  const shortfalls = projectedShortfalls(scenarios.data ?? []);
  const recent = recentAnalyses(scenarios.data ?? []).slice(0, RECENT);
  const pendingDocs = (documents.data?.items ?? []).filter((d) => d.status === "failed" || PROCESSING_STATUSES.has(d.status));
  const byHousehold = new Map<string, { scenarios: number; latest?: (typeof recent)[number] }>();
  for (const s of scenarios.data ?? []) {
    const e = byHousehold.get(s.household_id) ?? { scenarios: 0 };
    e.scenarios += 1;
    if (s.latest_run_at && (!e.latest || (e.latest.latest_run_at ?? "") < s.latest_run_at)) e.latest = s;
    byHousehold.set(s.household_id, e);
  }

  return (
    <div className="space-y-10">
      <PageHeader
        title="Overview"
        description="What needs attention across your households, documents and liquidity analyses."
        actions={headerActions}
      />

      {firstError ? (
        <ErrorState error={firstError} onRetry={reloadAll} />
      ) : !ready ? (
        <LoadingBlock rows={3} label="Loading overview…" />
      ) : (
        <NextActionPanel
          actions={actions}
          extra={
            actions[0]?.kind === "create_household" ? (
              <Button variant="secondary" onClick={createDemo} loading={creatingDemo}>
                Create demo household (synthetic)
              </Button>
            ) : undefined
          }
        />
      )}

      <Section
        title="Projected shortfalls"
        description="Scenarios whose latest run projects a cash shortfall, earliest first."
        action={
          <Link href="/scenarios" className="text-accent-ink underline-offset-2 hover:underline">
            All liquidity scenarios
          </Link>
        }
      >
        {scenarios.loading && !scenarios.data ? (
          <LoadingBlock rows={2} />
        ) : scenarios.error || !scenarios.data ? (
          <ErrorState error={scenarios.error} onRetry={() => void scenarios.reload()} />
        ) : shortfalls.length === 0 ? (
          <p className="text-sm text-ink-3">
            {recent.length
              ? "No latest run projects a shortfall within its horizon."
              : "No analyses have been run yet, so there is nothing to report."}
          </p>
        ) : (
          <TableWrap label="Projected shortfalls table">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Household</th>
                  <th className={th}>Scenario</th>
                  <th className={th}>First shortfall</th>
                  <th className={thNum}>Peak shortfall</th>
                  <th className={th}>Run</th>
                  <th className={th}>
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {shortfalls.map((s) => (
                  <tr key={s.id}>
                    <td className={td}>
                      <Link href={`/households/${s.household_id}`} className="underline-offset-2 hover:underline">
                        {s.household_name}
                      </Link>
                    </td>
                    <td className={td}>
                      <Link
                        href={`/households/${s.household_id}/scenarios/${s.id}`}
                        className="underline-offset-2 hover:underline"
                      >
                        {s.name}
                      </Link>
                    </td>
                    <td className={cx(td, "font-medium text-risk")}>Month {s.latest_first_shortfall_month}</td>
                    <td className={tdNum}>
                      {s.latest_peak_shortfall !== null ? formatMoney(s.latest_peak_shortfall, currency(s.household_id)) : EMPTY}
                    </td>
                    <td className={td}>{formatDateTime(s.latest_run_at)}</td>
                    <td className={td}>
                      <Link
                        href={`/households/${s.household_id}/runs/${s.latest_run_id}`}
                        className="font-medium text-accent-ink underline-offset-2 hover:underline"
                      >
                        Open analysis
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section
        title="Documents awaiting processing or review"
        description={
          review.data
            ? `${review.data.total} extracted ${review.data.total === 1 ? "term is" : "terms are"} waiting in the Review Queue.`
            : undefined
        }
        action={
          <>
            <Link href="/review" className="text-accent-ink underline-offset-2 hover:underline">
              Review Queue
            </Link>
            <span aria-hidden="true" className="text-ink-3">
              ·
            </span>
            <Link href="/documents" className="text-accent-ink underline-offset-2 hover:underline">
              All documents
            </Link>
          </>
        }
      >
        {documents.loading && !documents.data ? (
          <LoadingBlock rows={2} />
        ) : documents.error || !documents.data ? (
          <ErrorState error={documents.error} onRetry={() => void documents.reload()} />
        ) : pendingDocs.length === 0 ? (
          <p className="text-sm text-ink-3">No household documents are processing or failed.</p>
        ) : (
          <TableWrap label="Documents awaiting processing">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Document</th>
                  <th className={th}>Household</th>
                  <th className={th}>Status</th>
                  <th className={th}>Updated</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {pendingDocs.map((d) => (
                  <tr key={d.id}>
                    <td className={td}>
                      <Link href={docHref(d)} className="break-all text-accent-ink underline-offset-2 hover:underline">
                        {d.original_filename}
                      </Link>{" "}
                      {d.is_demo_fixture && <SyntheticBadge />}
                    </td>
                    <td className={td}>
                      {households.data?.items.find((h) => h.id === d.household_id)?.name ?? EMPTY}
                    </td>
                    <td className={td}>
                      <DocumentStatusBadge status={d.status} />
                      {d.status === "failed" && d.error_message && (
                        <span className="mt-1 block text-xs text-risk">{d.error_message}</span>
                      )}
                    </td>
                    <td className={td}>{formatDateTime(d.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section title="Recently completed analyses">
        {scenarios.loading && !scenarios.data ? (
          <LoadingBlock rows={2} />
        ) : scenarios.error || !scenarios.data ? null : recent.length === 0 ? (
          <p className="text-sm text-ink-3">
            No analyses yet. Open a household, create a liquidity scenario and run it.
          </p>
        ) : (
          <TableWrap label="Recently completed analyses table">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Run</th>
                  <th className={th}>Scenario</th>
                  <th className={th}>Household</th>
                  <th className={th}>Result</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {recent.map((s) => (
                  <tr key={s.id}>
                    <td className={td}>
                      <Link
                        href={`/households/${s.household_id}/runs/${s.latest_run_id}`}
                        className="text-accent-ink underline-offset-2 hover:underline"
                      >
                        {formatDateTime(s.latest_run_at)}
                      </Link>
                    </td>
                    <td className={td}>{s.name}</td>
                    <td className={td}>{s.household_name}</td>
                    <td className={td}>
                      {s.latest_first_shortfall_month === null ? (
                        <span className="text-accent-ink">No shortfall in horizon</span>
                      ) : (
                        <span className="text-risk">Shortfall from month {s.latest_first_shortfall_month}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>

      <Section
        title="Households monitored"
        action={
          <Link href="/households" className="text-accent-ink underline-offset-2 hover:underline">
            All households
          </Link>
        }
      >
        {households.loading && !households.data ? (
          <LoadingBlock rows={3} />
        ) : households.error || !households.data ? (
          <ErrorState error={households.error} onRetry={() => void households.reload()} />
        ) : households.data.items.length === 0 ? (
          <EmptyState title="No households yet" action={headerActions}>
            Create a household to record assets, obligations and private agreements, or explore OndhoDeck with a demo
            household that uses <strong>synthetic data and synthetic sample contracts</strong>, labelled throughout.
          </EmptyState>
        ) : (
          <TableWrap label="Households">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Household</th>
                  <th className={th}>Your role</th>
                  <th className={th}>Latest analysis</th>
                  <th className={th}>Updated</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {households.data.items.map((h) => {
                  const latest = byHousehold.get(h.id)?.latest;
                  return (
                    <tr key={h.id}>
                      <td className={td}>
                        <Link href={`/households/${h.id}`} className="font-medium text-accent-ink underline-offset-2 hover:underline">
                          {h.name}
                        </Link>{" "}
                        {h.is_demo && <SyntheticBadge />}
                      </td>
                      <td className={td}>{humanize(h.role)}</td>
                      <td className={td}>
                        {latest ? (
                          <Link
                            href={`/households/${h.id}/runs/${latest.latest_run_id}`}
                            className="underline-offset-2 hover:underline"
                          >
                            {latest.latest_first_shortfall_month === null
                              ? "No shortfall"
                              : `Shortfall from month ${latest.latest_first_shortfall_month}`}
                          </Link>
                        ) : (
                          <span className="text-ink-3">Not analysed</span>
                        )}
                      </td>
                      <td className={td}>{formatDateTime(h.updated_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Section>
    </div>
  );
}
