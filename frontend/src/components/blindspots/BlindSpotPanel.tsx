"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
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
  Button,
  Card,
  ErrorState,
  LoadingBlock,
  Notice,
  SelectField,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
  type BadgeTone,
} from "@/components/ui";
import { RunErrorState } from "@/components/runs/TermConflict";
import { useToast } from "@/components/Toast";
import { resolveApiUrl } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDate, formatDateTime, formatMoney, formatNumber, humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { BlindSpotComparison, BlindSpotOut, BlindSpotRisk } from "@/lib/types";

const SEVERITY_TONE: Record<string, BadgeTone> = { critical: "danger", high: "warning", moderate: "neutral" };
const BLIND_SPOT_EXPLAINER = "Not visible in a paper-wealth view: the paper-wealth model shows no shortfall, or a later one.";

/** Series colours: the baseline is a neutral dashed reference; the selected variant is the one coloured line. */
const BASELINE_COLOR = "#6b665e";
const VARIANT_COLOR = "#1d8052";

const EXPORT_POLL_MS = 1500;
const EXPORT_MAX_POLLS = 80;

function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity] ?? "neutral"}>{humanize(severity)}</Badge>;
}

function monthText(m: number | null | undefined) {
  return m === null || m === undefined ? "None" : `Month ${m}`;
}

function RiskDetail({ risk, currency }: { risk: BlindSpotRisk; currency: string }) {
  return (
    <div className="space-y-3 bg-surface-muted px-4 py-3 text-sm">
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Assumptions changed in this variant</p>
          {risk.changes.length ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {risk.changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-ink-3">None (baseline scenario).</p>
          )}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Binding constraints in the first shortfall month</p>
          {risk.binding_in_first_shortfall_month.length ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {risk.binding_in_first_shortfall_month.map((b, i) => (
                <li key={i}>{humanize(b)}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-ink-3">None recorded.</p>
          )}
          <p className="mt-2 text-xs text-ink-3">
            Paper-wealth first shortfall: {monthText(risk.paper_wealth_first_shortfall_month)}
          </p>
        </div>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Contributing contract rules</p>
        {risk.contributing_rules.length === 0 ? (
          <p className="mt-1 text-ink-3">No single contract rule reduces the peak deficit when relaxed.</p>
        ) : (
          <ul className="mt-2 space-y-3">
            {risk.contributing_rules.map((r, i) => (
              <li key={`${r.rule}-${i}`} className="rounded-md border border-line bg-surface p-3">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{humanize(r.rule)}</span>
                  <span className="text-xs text-ink-3 tabular-nums">
                    relaxing it reduces the peak deficit by {formatMoney(r.peak_shortfall_reduction, currency)}
                  </span>
                  {r.removes_shortfall && <Badge tone="info">Removes the shortfall on its own</Badge>}
                </p>
                <p className="mt-1 text-ink-2">{r.basis}</p>
                {r.evidence.length > 0 && (
                  <ul className="mt-2 space-y-2">
                    {r.evidence.map((ev, j) => (
                      <li key={j}>
                        <blockquote className="evidence-quote border-l-2 border-accent pl-3">“{ev.quote}”</blockquote>
                        <p className="mt-0.5 pl-3 text-xs text-ink-3">
                          {ev.document} · PDF page {ev.pdf_page}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function RisksTable({ risks, currency }: { risks: BlindSpotRisk[]; currency: string }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <TableWrap label="Ranked liquidity risks">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={thNum}>Rank</th>
            <th className={th}>Variant</th>
            <th className={th}>Severity</th>
            <th className={th}>Blind spot</th>
            <th className={th}>First shortfall</th>
            <th className={thNum}>Peak deficit</th>
            <th className={thNum}>Months of spending</th>
            <th className={th}>
              <span className="sr-only">Details</span>
            </th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {risks.map((r) => {
            const expanded = open === r.variant;
            return (
              <Fragment key={r.variant}>
                <tr>
                  <td className={tdNum}>{r.rank}</td>
                  <td className={td}>{r.label}</td>
                  <td className={td}>
                    <SeverityBadge severity={r.severity} />
                  </td>
                  <td className={td}>
                    {r.blind_spot ? (
                      <Badge tone="warning" title={BLIND_SPOT_EXPLAINER}>
                        Blind spot
                      </Badge>
                    ) : (
                      <span className="text-ink-3">Visible on paper</span>
                    )}
                  </td>
                  <td className={td}>{monthText(r.first_shortfall_month)}</td>
                  <td className={tdNum}>{formatMoney(r.peak_shortfall, currency)}</td>
                  <td className={tdNum}>
                    {r.peak_in_months_of_spending === null ? EMPTY : formatNumber(r.peak_in_months_of_spending, 1)}
                  </td>
                  <td className={td}>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={expanded}
                      aria-label={`${expanded ? "Hide" : "Show"} details for ${r.label}`}
                      onClick={() => setOpen(expanded ? null : r.variant)}
                    >
                      {expanded ? "Hide" : "Details"}
                    </Button>
                  </td>
                </tr>
                {expanded && (
                  <tr>
                    <td colSpan={8} className="p-0">
                      <RiskDetail risk={r} currency={currency} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </TableWrap>
  );
}

function ComparisonTable({ rows, currency }: { rows: BlindSpotComparison[]; currency: string }) {
  return (
    <TableWrap label="Scenario comparison">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={th}>Variant</th>
            <th className={th}>Contract-aware first shortfall</th>
            <th className={thNum}>Contract-aware peak deficit</th>
            <th className={thNum}>Contract-aware min cash</th>
            <th className={th}>Paper-wealth first shortfall</th>
            <th className={thNum}>Paper-wealth peak deficit</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {rows.map((c) => (
            <tr key={c.variant}>
              <td className={td}>
                {c.label}
                {c.changes.length > 0 && <span className="block text-xs text-ink-3">{c.changes.join("; ")}</span>}
              </td>
              <td className={td}>{monthText(c.contract_aware.first_shortfall_month)}</td>
              <td className={tdNum}>{formatMoney(c.contract_aware.peak_shortfall, currency)}</td>
              <td className={tdNum}>{formatMoney(c.contract_aware.min_cash, currency)}</td>
              <td className={td}>{monthText(c.paper_wealth.first_shortfall_month)}</td>
              <td className={tdNum}>{formatMoney(c.paper_wealth.peak_shortfall, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function buildCashSeries(baseline: BlindSpotComparison | undefined, variant: BlindSpotComparison | undefined) {
  const n = Math.max(baseline?.monthly_cash.length ?? 0, variant?.monthly_cash.length ?? 0);
  return Array.from({ length: n }, (_, i) => ({
    month: i + 1,
    baseline: baseline?.monthly_cash[i] ?? null,
    variant: variant?.monthly_cash[i] ?? null,
  }));
}

function CashChart({ rows, currency }: { rows: BlindSpotComparison[]; currency: string }) {
  const baseline = rows[0];
  const others = rows.slice(1);
  const [selected, setSelected] = useState(others[0]?.variant ?? "");
  const variant = others.find((r) => r.variant === selected);
  const data = useMemo(() => buildCashSeries(baseline, variant), [baseline, variant]);
  if (!baseline) return null;
  return (
    <figure aria-label="Contract-aware month-end cash: baseline versus a selected variant" className="space-y-2">
      {others.length > 0 && (
        <div className="max-w-sm">
          <SelectField
            label="Compare baseline with"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            options={others.map((o) => ({ value: o.variant, label: o.label }))}
          />
        </div>
      )}
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke="#ece8e1" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#5c5852" }} stroke="#d4cfc6" tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "#5c5852" }}
              stroke="#d4cfc6"
              tickLine={false}
              width={72}
              tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
            />
            <Tooltip
              formatter={(value: number | string, name: string) => [formatMoney(value, currency), name]}
              labelFormatter={(m: number) => `Month ${m}`}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: "#3f3f3f" }} />
            <ReferenceLine y={0} stroke="#3f3f3f" strokeWidth={1} label={{ value: "Zero cash", position: "insideTopRight", fontSize: 11, fill: "#5c5852" }} />
            <Line
              type="linear"
              dataKey="baseline"
              name={baseline.label}
              stroke={BASELINE_COLOR}
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
            {variant && (
              <Line
                type="linear"
                dataKey="variant"
                name={variant.label}
                stroke={VARIANT_COLOR}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-xs text-ink-3">
        Contract-aware month-end cash. Baseline dashed; selected variant solid. Below the zero line is a shortfall. The
        comparison table lists the same results.
      </figcaption>
    </figure>
  );
}

function ExportButton({ householdId, reportId }: { householdId: string; reportId: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      let exp = await endpoints.requestExport(householdId, { kind: "blind_spot_pdf", blind_spot_report_id: reportId });
      for (let i = 0; i < EXPORT_MAX_POLLS && (exp.status === "queued" || exp.status === "running"); i++) {
        await new Promise((r) => setTimeout(r, EXPORT_POLL_MS));
        exp = await endpoints.getExport(exp.id);
      }
      if (exp.status === "ready") {
        const signed = await endpoints.downloadExport(exp.id);
        window.open(resolveApiUrl(signed.url), "_blank", "noopener,noreferrer");
        toast.success("Blind-spot report ready");
      } else if (exp.status === "failed") {
        toast.error(exp.error_message ?? "The export failed.");
      } else {
        toast.success("Export still in progress", "It will appear on the household Exports page when ready.");
      }
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button size="sm" variant="secondary" onClick={run} loading={busy}>
      Export PDF
    </Button>
  );
}

export function BlindSpotReport({ report, currency }: { report: BlindSpotOut; currency: string }) {
  const r = report.result;
  return (
    <div className="space-y-4">
      <Notice tone="info" title="What this is — and is not">
        {r.disclaimer}
      </Notice>
      <p className="text-sm text-ink-2">
        <span className="font-medium text-ink">
          {r.summary.risks} of {r.summary.variants} variants run out of cash
        </span>{" "}
        under contract terms · {r.summary.blind_spots} {r.summary.blind_spots === 1 ? "is a blind spot" : "are blind spots"}{" "}
        · {r.summary.critical} critical · terms as of {formatDate(report.as_of_date)} · monthly spending{" "}
        <span className="tabular-nums">{formatMoney(r.monthly_spending, currency)}</span>
      </p>
      {report.warnings.length > 0 && (
        <Notice tone="warning" title="Warnings">
          <ul className="list-disc space-y-0.5 pl-5">
            {report.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Notice>
      )}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-ink">Ranked risks</h3>
        <p className="text-xs text-ink-3">
          A <strong>blind spot</strong> is a shortfall not visible in a paper-wealth view: treating illiquid holdings as
          sellable shows no shortfall, or a later one. Ranking: severity, then blind spots first, then earlier shortfall,
          then larger peak deficit.
        </p>
        {r.risks.length === 0 ? (
          <Notice tone="success">No variant produced a contract-aware shortfall within the horizon.</Notice>
        ) : (
          <RisksTable risks={r.risks} currency={currency} />
        )}
      </section>
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-ink">Scenario comparison</h3>
        <CashChart rows={r.comparison} currency={currency} />
        <ComparisonTable rows={r.comparison} currency={currency} />
      </section>
      <details className="text-xs text-ink-3">
        <summary className="cursor-pointer select-none">Method</summary>
        <p className="mt-1 whitespace-pre-wrap">{r.method}</p>
      </details>
    </div>
  );
}

export function BlindSpotPanel({
  householdId,
  scenarioId,
  currency,
  canEdit,
}: {
  householdId: string;
  scenarioId: string;
  currency: string;
  canEdit: boolean;
}) {
  const toast = useToast();
  const history = useApiQuery(
    () => endpoints.listBlindSpotReports(householdId, { scenario_id: scenarioId, limit: 20 }),
    [householdId, scenarioId],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [current, setCurrent] = useState<BlindSpotOut | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<unknown>(null);

  const latestId = history.data?.items[0]?.id ?? null;
  const wantedId = selectedId ?? latestId;
  const detail = useApiQuery(
    () => endpoints.getBlindSpotReport(wantedId as string),
    [wantedId],
    Boolean(wantedId) && current?.id !== wantedId,
  );
  useEffect(() => {
    if (detail.data && detail.data.id === wantedId) setCurrent(detail.data);
  }, [detail.data, wantedId]);

  const run = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const rep = await endpoints.runBlindSpots(scenarioId);
      setCurrent(rep);
      setSelectedId(rep.id);
      toast.success("Blind-spot check complete");
      void history.reload();
    } catch (e) {
      setRunError(e);
    } finally {
      setRunning(false);
    }
  };

  const shown = current && current.id === wantedId ? current : null;

  return (
    <Card
      title="Liquidity blind-spot check"
      actions={
        <>
          {shown && <ExportButton householdId={householdId} reportId={shown.id} />}
          {canEdit && (
            <Button size="sm" onClick={run} loading={running}>
              Run blind-spot check
            </Button>
          )}
        </>
      }
    >
      <div id="blind-spots" className="space-y-4">
        <p className="text-sm text-ink-3">
          Applies a fixed set of deterministic stress variants to this saved scenario and ranks the ones where approved
          contract terms leave the household short of cash. Save scenario changes before running.
        </p>
        <RunErrorState error={runError} />
        {(history.data?.items.length ?? 0) > 1 && (
          <div className="max-w-md">
            <SelectField
              label="Report"
              value={wantedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
              options={(history.data?.items ?? []).map((h) => ({
                value: h.id,
                label: `${formatDateTime(h.created_at)} · ${h.risk_count} risks · ${h.blind_spot_count} blind spots`,
              }))}
            />
          </div>
        )}
        {history.loading && !history.data ? (
          <LoadingBlock rows={2} />
        ) : history.error ? (
          <ErrorState error={history.error} onRetry={() => void history.reload()} />
        ) : shown ? (
          <BlindSpotReport report={shown} currency={currency} />
        ) : wantedId && detail.loading ? (
          <LoadingBlock rows={3} label="Loading report…" />
        ) : detail.error ? (
          <ErrorState error={detail.error} onRetry={() => void detail.reload()} />
        ) : (
          <p className="text-sm text-ink-3">No blind-spot report for this scenario yet.</p>
        )}
      </div>
    </Card>
  );
}
