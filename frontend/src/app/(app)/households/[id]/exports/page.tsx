"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Pagination,
  SelectField,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { ExportStatusBadge } from "@/components/badges";
import { useHousehold } from "@/components/household/HouseholdContext";
import { useExportDownload } from "@/components/reports/useExportDownload";
import { useToast } from "@/components/Toast";
import { itemsOf } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { exportKindLabel } from "@/lib/exportKinds";
import { formatBytes, formatDateTime } from "@/lib/format";
import { describeError, useApiQuery, usePolling } from "@/lib/hooks";
import type { ExportKind } from "@/lib/types";

const LIMIT = 20;
const RUN_KINDS: ExportKind[] = ["report_pdf", "simulation_csv", "results_json"];
const TERM_KINDS: ExportKind[] = ["constraints_csv", "constraints_json"];

function Source({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <p className="text-sm text-ink-3">{description}</p>
      </div>
      {children}
    </section>
  );
}

export default function ExportsPage() {
  const { household } = useHousehold();
  const hid = household.id;
  const params = useSearchParams();
  const toast = useToast();
  const { downloading, download } = useExportDownload();
  const [offset, setOffset] = useState(0);
  // Links from an analysis or a blind-spot check preselect it; otherwise the latest one is used.
  const [runId, setRunId] = useState(params?.get("run_id") ?? "");
  const [spotId, setSpotId] = useState(params?.get("blind_spot_report_id") ?? "");
  const [requesting, setRequesting] = useState<ExportKind | null>(null);

  const runs = useApiQuery(() => endpoints.listRuns(hid, { limit: 50 }), [hid]);
  const spots = useApiQuery(() => endpoints.listBlindSpotReports(hid, { limit: 50 }), [hid]);
  const scenarios = useApiQuery(async () => itemsOf(await endpoints.listScenarios(hid, { limit: 100 })), [hid]);
  const exps = useApiQuery(() => endpoints.listExports(hid, { limit: LIMIT, offset }), [hid, offset]);
  const pending = exps.data?.items.some((e) => e.status === "queued" || e.status === "running") ?? false;
  usePolling(() => void exps.reload(), 3000, pending);

  const runOptions = useMemo(() => {
    const opts = (runs.data?.items ?? []).map((r) => ({
      value: r.id,
      label: `${r.scenario_name || "Scenario"} · ${formatDateTime(r.created_at)}`,
    }));
    if (runId && !opts.some((o) => o.value === runId)) opts.unshift({ value: runId, label: "Linked analysis" });
    return opts;
  }, [runs.data, runId]);

  const spotOptions = useMemo(() => {
    const names = new Map((scenarios.data ?? []).map((s) => [s.id, s.name]));
    const opts = (spots.data?.items ?? []).map((s) => ({
      value: s.id,
      label: `${names.get(s.scenario_id) ?? "Scenario"} · ${formatDateTime(s.created_at)} · ${s.blind_spot_count} blind spot${s.blind_spot_count === 1 ? "" : "s"}`,
    }));
    if (spotId && !opts.some((o) => o.value === spotId)) opts.unshift({ value: spotId, label: "Linked blind-spot check" });
    return opts;
  }, [spots.data, scenarios.data, spotId]);

  const selectedRun = runId || runOptions[0]?.value || "";
  const selectedSpot = spotId || spotOptions[0]?.value || "";

  const request = async (kind: ExportKind) => {
    setRequesting(kind);
    try {
      await endpoints.requestExport(hid, {
        kind,
        run_id: RUN_KINDS.includes(kind) ? selectedRun : undefined,
        blind_spot_report_id: kind === "blind_spot_pdf" ? selectedSpot : undefined,
      });
      toast.success(`${exportKindLabel(kind)} requested`, "It is listed below and can be downloaded when ready.");
      if (offset) setOffset(0);
      else void exps.reload();
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setRequesting(null);
    }
  };

  const kindButton = (kind: ExportKind, primary = false) => (
    <Button
      key={kind}
      size="sm"
      variant={primary ? "primary" : "secondary"}
      loading={requesting === kind}
      disabled={requesting !== null}
      onClick={() => void request(kind)}
    >
      {exportKindLabel(kind)}
    </Button>
  );

  return (
    <div className="space-y-5">
      <Card title="Create a report">
        <div className="space-y-6">
          <Source title="From an analysis" description="A liquidity report or data export built from one completed scenario run.">
            {runs.loading && !runs.data ? (
              <LoadingBlock rows={1} />
            ) : runs.error ? (
              <ErrorState error={runs.error} onRetry={() => void runs.reload()} />
            ) : runOptions.length === 0 ? (
              <p className="text-sm text-ink-2">
                No analyses yet.{" "}
                <Link href={`/households/${hid}/scenarios`} className="text-accent-ink underline underline-offset-2">
                  Run a scenario
                </Link>{" "}
                to create a liquidity report.
              </p>
            ) : (
              <>
                <SelectField
                  label="Analysis"
                  value={selectedRun}
                  onChange={(e) => setRunId(e.target.value)}
                  options={runOptions}
                  className="max-w-xl"
                />
                <div className="flex flex-wrap gap-2">{RUN_KINDS.map((k) => kindButton(k, k === "report_pdf"))}</div>
              </>
            )}
          </Source>

          <Source title="From a blind-spot check" description="The findings of one completed blind-spot check, as a PDF.">
            {spots.loading && !spots.data ? (
              <LoadingBlock rows={1} />
            ) : spots.error ? (
              <ErrorState error={spots.error} onRetry={() => void spots.reload()} />
            ) : spotOptions.length === 0 ? (
              <p className="text-sm text-ink-2">
                No blind-spot checks yet. Open a{" "}
                <Link href={`/households/${hid}/scenarios`} className="text-accent-ink underline underline-offset-2">
                  scenario
                </Link>{" "}
                and choose <strong>Run blind-spot check</strong>.
              </p>
            ) : (
              <>
                <SelectField
                  label="Blind-spot check"
                  value={selectedSpot}
                  onChange={(e) => setSpotId(e.target.value)}
                  options={spotOptions}
                  className="max-w-xl"
                />
                <div className="flex flex-wrap gap-2">{kindButton("blind_spot_pdf")}</div>
              </>
            )}
          </Source>

          <Source title="Household terms" description="The household's contract terms, for use outside OndhoDeck.">
            <div className="flex flex-wrap gap-2">{TERM_KINDS.map((k) => kindButton(k))}</div>
          </Source>
        </div>
      </Card>

      <Card title="Reports and exports">
        {exps.loading && !exps.data ? (
          <LoadingBlock rows={3} label="Loading reports…" />
        ) : exps.error || !exps.data ? (
          <ErrorState error={exps.error} onRetry={() => void exps.reload()} />
        ) : exps.data.items.length === 0 ? (
          <EmptyState title="No reports yet">Create a report above; it will be listed here when it is ready.</EmptyState>
        ) : (
          <>
            <TableWrap label="Reports and exports">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>Status</th>
                    <th className={th}>Type</th>
                    <th className={th}>Created</th>
                    <th className={th}>Source</th>
                    <th className={thNum}>Size</th>
                    <th className={th}>
                      <span className="sr-only">Download</span>
                    </th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {exps.data.items.map((x) => (
                    <tr key={x.id}>
                      <td className={td}>
                        <ExportStatusBadge status={x.status} />
                        {x.status === "failed" && (
                          <span className="mt-1 block max-w-xs text-xs text-risk">{x.error_message || "The export failed."}</span>
                        )}
                      </td>
                      <td className={td}>
                        {exportKindLabel(x.kind)}
                        {x.filename && <span className="block break-all text-xs text-ink-3">{x.filename}</span>}
                      </td>
                      <td className={td}>{formatDateTime(x.created_at)}</td>
                      <td className={td}>
                        {x.run_id ? (
                          <Link href={`/households/${hid}/runs/${x.run_id}`} className="text-accent-ink underline-offset-2 hover:underline">
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
                            onClick={() => void download(x.id)}
                            loading={downloading === x.id}
                            aria-label={`Download ${exportKindLabel(x.kind)} created ${formatDateTime(x.created_at)}`}
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
            <Pagination total={exps.data.total} limit={exps.data.limit || LIMIT} offset={exps.data.offset} onChange={setOffset} />
          </>
        )}
      </Card>

      <p className="small-print">
        Reports describe modelled projections from the approved terms and scenario assumptions at the time of each run.
        They are not guaranteed outcomes or advice.
      </p>
    </div>
  );
}
