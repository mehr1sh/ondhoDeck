"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Button,
  EmptyState,
  ErrorState,
  FilterInput,
  FilterSelect,
  LinkButton,
  LoadingBlock,
  PageHeader,
  Section,
  SortTh,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
  useSortedRows,
} from "@/components/ui";
import { ExportStatusBadge } from "@/components/badges";
import { endpoints } from "@/lib/endpoints";
import { EXPORT_KIND_LABELS, exportKindLabel } from "@/lib/exportKinds";
import { formatBytes, formatDate, formatDateTime } from "@/lib/format";
import { useApiQuery, usePolling } from "@/lib/hooks";
import type { ReportBlindSpotItem, ReportExportItem } from "@/lib/types";
import { useExportDownload } from "./useExportDownload";

const LIMIT = 200;

function HowTo() {
  return (
    <div className="grid gap-6 border-y border-line py-5 text-sm sm:grid-cols-2">
      <div>
        <h2 className="font-display text-base text-ink">Liquidity report (PDF)</h2>
        <p className="mt-1 text-ink-2">
          Open an analysis result and choose <strong>Create report</strong>, or request one from a household&apos;s Reports
          tab. It needs a completed run of a liquidity scenario.
        </p>
        <Link href="/scenarios" className="mt-2 inline-block text-accent-ink underline underline-offset-2">
          Find an analysis in Liquidity Scenarios
        </Link>
      </div>
      <div>
        <h2 className="font-display text-base text-ink">Blind-spot report (PDF)</h2>
        <p className="mt-1 text-ink-2">
          Run the blind-spot check on a scenario page, then use <strong>Export PDF</strong>. Each completed check is listed
          below and can be exported later.
        </p>
        <Link href="/scenarios" className="mt-2 inline-block text-accent-ink underline underline-offset-2">
          Choose a scenario to check
        </Link>
      </div>
    </div>
  );
}

export function ReportsView() {
  const q = useApiQuery(() => endpoints.myReports(LIMIT), []);
  const { downloading, download } = useExportDownload();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");

  const exportsAll = useMemo(() => q.data?.exports ?? [], [q.data]);
  const spots = useMemo(() => q.data?.blind_spot_reports ?? [], [q.data]);
  const pending = exportsAll.some((e) => e.status === "queued" || e.status === "running");
  usePolling(() => void q.reload(), 3000, pending);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return exportsAll.filter(
      (e) =>
        (!kind || e.kind === kind) &&
        (!s || e.household_name.toLowerCase().includes(s) || (e.filename ?? "").toLowerCase().includes(s)),
    );
  }, [exportsAll, search, kind]);

  const sortedExports = useSortedRows<ReportExportItem, "created" | "household" | "kind" | "status">(
    filtered,
    {
      created: (e) => e.created_at,
      household: (e) => e.household_name,
      kind: (e) => exportKindLabel(e.kind),
      status: (e) => e.status,
    },
    { key: "created", dir: "desc" },
  );
  const sortedSpots = useSortedRows<ReportBlindSpotItem, "created" | "household" | "scenario">(
    spots,
    { created: (r) => r.created_at, household: (r) => r.household_name, scenario: (r) => r.scenario_name },
    { key: "created", dir: "desc" },
  );
  const exportedSpotIds = new Set(
    exportsAll.filter((e) => e.blind_spot_report_id && e.status !== "failed").map((e) => e.blind_spot_report_id),
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title="Reports"
        description="Liquidity and blind-spot reports, and data exports, across every household you can access."
        actions={
          <LinkButton href="/scenarios" variant="primary">
            Open liquidity scenarios
          </LinkButton>
        }
      />
      <HowTo />

      {q.loading && !q.data ? (
        <LoadingBlock rows={4} label="Loading reports…" />
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : exportsAll.length === 0 && spots.length === 0 ? (
        <EmptyState
          title="No reports yet"
          action={
            <LinkButton href="/scenarios" variant="primary">
              Open liquidity scenarios
            </LinkButton>
          }
        >
          Run a liquidity scenario for a household, then create a liquidity report from its analysis result, or run a
          blind-spot check and export it as a PDF.
        </EmptyState>
      ) : (
        <>
          <Section title="Reports and exports" description="Files generated from analyses and reviewed terms.">
            {exportsAll.length === 0 ? (
              <p className="text-sm text-ink-3">No reports or exports have been requested yet.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-end gap-3">
                  <FilterInput label="Filter by household or file" value={search} onChange={setSearch} />
                  <FilterSelect
                    label="Type"
                    value={kind}
                    onChange={setKind}
                    options={[
                      { value: "", label: "All types" },
                      ...Object.entries(EXPORT_KIND_LABELS).map(([value, label]) => ({ value, label })),
                    ]}
                  />
                </div>
                {sortedExports.rows.length === 0 ? (
                  <p className="text-sm text-ink-3">No reports match the filter.</p>
                ) : (
                  <TableWrap label="Reports and exports table">
                    <table className={tableClass}>
                      <thead>
                        <tr>
                          <SortTh label="Status" sortKey="status" sort={sortedExports.sort} onSort={sortedExports.toggle} />
                          <SortTh label="Household" sortKey="household" sort={sortedExports.sort} onSort={sortedExports.toggle} />
                          <SortTh label="Type" sortKey="kind" sort={sortedExports.sort} onSort={sortedExports.toggle} />
                          <SortTh label="Created" sortKey="created" sort={sortedExports.sort} onSort={sortedExports.toggle} />
                          <th className={th}>Source</th>
                          <th className={thNum}>Size</th>
                          <th className={th}>
                            <span className="sr-only">Download</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody className={tbodyClass}>
                        {sortedExports.rows.map((x) => (
                          <tr key={x.id}>
                            <td className={td}>
                              <ExportStatusBadge status={x.status} />
                              {x.status === "failed" && (
                                <span className="mt-1 block max-w-xs text-xs text-risk">
                                  {x.error_message || "The export failed."}
                                </span>
                              )}
                            </td>
                            <td className={td}>
                              <Link href={`/households/${x.household_id}`} className="underline-offset-2 hover:underline">
                                {x.household_name}
                              </Link>
                            </td>
                            <td className={td}>
                              {exportKindLabel(x.kind)}
                              {x.filename && <span className="block break-all text-xs text-ink-3">{x.filename}</span>}
                            </td>
                            <td className={td}>{formatDateTime(x.created_at)}</td>
                            <td className={td}>
                              {x.run_id ? (
                                <Link
                                  href={`/households/${x.household_id}/runs/${x.run_id}`}
                                  className="text-accent-ink underline-offset-2 hover:underline"
                                >
                                  Analysis
                                </Link>
                              ) : x.blind_spot_report_id ? (
                                <span className="text-ink-2">Blind-spot check</span>
                              ) : (
                                <span className="text-ink-3">Household terms</span>
                              )}
                            </td>
                            <td className={tdNum}>{formatBytes(x.size_bytes)}</td>
                            <td className={td}>
                              {x.status === "ready" ? (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() => download(x.id)}
                                  loading={downloading === x.id}
                                  aria-label={`Download ${exportKindLabel(x.kind)} for ${x.household_name}`}
                                >
                                  Download
                                </Button>
                              ) : x.status === "failed" ? null : (
                                <span className="text-xs text-ink-3">Preparing…</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                )}
              </>
            )}
          </Section>

          <Section
            title="Blind-spot checks"
            description="Completed blind-spot checks. Open the scenario to see the findings, or export a PDF."
          >
            {spots.length === 0 ? (
              <p className="text-sm text-ink-3">
                No blind-spot checks yet. Open a scenario and choose <strong>Run blind-spot check</strong>.
              </p>
            ) : (
              <TableWrap label="Blind-spot checks table">
                <table className={tableClass}>
                  <thead>
                    <tr>
                      <SortTh label="Household" sortKey="household" sort={sortedSpots.sort} onSort={sortedSpots.toggle} />
                      <SortTh label="Scenario" sortKey="scenario" sort={sortedSpots.sort} onSort={sortedSpots.toggle} />
                      <th className={th}>As of</th>
                      <th className={thNum}>Risks</th>
                      <th className={thNum}>Blind spots</th>
                      <SortTh label="Created" sortKey="created" sort={sortedSpots.sort} onSort={sortedSpots.toggle} />
                      <th className={th}>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className={tbodyClass}>
                    {sortedSpots.rows.map((r) => (
                      <tr key={r.id}>
                        <td className={td}>
                          <Link href={`/households/${r.household_id}`} className="underline-offset-2 hover:underline">
                            {r.household_name}
                          </Link>
                        </td>
                        <td className={td}>
                          <Link
                            href={`/households/${r.household_id}/scenarios/${r.scenario_id}`}
                            className="text-accent-ink underline-offset-2 hover:underline"
                          >
                            {r.scenario_name}
                          </Link>
                        </td>
                        <td className={td}>{formatDate(r.as_of_date)}</td>
                        <td className={tdNum}>{r.risk_count}</td>
                        <td className={cx(tdNum, r.blind_spot_count > 0 && "font-semibold text-risk")}>
                          {r.blind_spot_count}
                        </td>
                        <td className={td}>{formatDateTime(r.created_at)}</td>
                        <td className={td}>
                          {exportedSpotIds.has(r.id) ? (
                            <span className="text-xs text-ink-3">PDF listed above</span>
                          ) : (
                            <Link
                              href={`/households/${r.household_id}/exports?blind_spot_report_id=${r.id}`}
                              className="text-xs font-medium text-accent-ink underline underline-offset-2"
                            >
                              Create PDF
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Section>
        </>
      )}
      <p className="small-print">
        Reports describe modelled projections from the approved terms and scenario assumptions at the time of each run.
        They are not guaranteed outcomes or advice.
      </p>
    </div>
  );
}
