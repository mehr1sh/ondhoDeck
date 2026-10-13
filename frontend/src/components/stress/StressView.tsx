"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  Stat,
  TableWrap,
  TextField,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { DictTable } from "@/components/DictTable";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, formatPercent, parseDecimal } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import type { StressGridPoint, StressOut, StressRequest } from "@/lib/types";

export function stressGrid(result: StressOut): StressGridPoint[] {
  const grid = (result.search as { grid?: unknown }).grid;
  if (!Array.isArray(grid)) return [];
  return grid
    .filter((g): g is StressGridPoint => !!g && typeof g === "object" && "equity_drawdown" in g && "min_cash" in g)
    .map((g) => ({ ...g, equity_drawdown: Number(g.equity_drawdown), min_cash: Number(g.min_cash) }))
    .sort((a, b) => a.equity_drawdown - b.equity_drawdown);
}

function GridChart({ result, currency }: { result: StressOut; currency: string }) {
  const grid = stressGrid(result);
  const boundary = parseDecimal(result.boundary_drawdown);
  if (!grid.length) return <p className="text-sm text-slate-600">The search grid was not included in this result.</p>;
  return (
    <figure aria-label="Minimum cash by equity drawdown">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={grid} margin={{ top: 16, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="equity_drawdown"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => formatPercent(v, 0)}
              tick={{ fontSize: 12, fill: "#475569" }}
              stroke="#cbd5e1"
            />
            <YAxis
              width={72}
              tickFormatter={(v: number) => formatMoney(v, currency, { compact: true })}
              tick={{ fontSize: 12, fill: "#475569" }}
              stroke="#cbd5e1"
            />
            <Tooltip
              formatter={(v: number | string) => [formatMoney(v, currency), "Minimum cash"]}
              labelFormatter={(d: number) => `Equity drawdown ${formatPercent(d, 1)}`}
            />
            <ReferenceLine y={0} stroke="#64748b" strokeWidth={1.5} />
            {boundary !== null && (
              <ReferenceLine
                x={boundary}
                stroke="#b91c1c"
                strokeDasharray="4 3"
                label={{ value: `Boundary ${formatPercent(boundary, 1)}`, position: "top", fontSize: 11, fill: "#7f1d1d" }}
              />
            )}
            <Line type="monotone" dataKey="min_cash" name="Minimum cash" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 text-xs text-slate-600">
        Minimum cash over the horizon (contract-aware model) at each equity drawdown tested. The dashed vertical line marks
        the boundary drawdown where cash first goes below zero.
      </figcaption>
    </figure>
  );
}

function StressResult({ result, currency }: { result: StressOut; currency: string }) {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Boundary drawdown"
          value={result.found ? formatPercent(result.boundary_drawdown, 2) : "Not reached"}
          tone={result.found ? "danger" : "success"}
          hint={result.found ? "Smallest equity drawdown that causes a shortfall" : "No shortfall within the searched range"}
        />
        <Stat label="Last safe drawdown" value={result.last_safe_drawdown !== null ? formatPercent(result.last_safe_drawdown, 2) : EMPTY} />
        <Stat label="First failure month" value={result.first_shortfall_month ?? EMPTY} />
        <Stat label="Deficit at boundary" value={formatMoney(result.shortfall_amount, currency)} />
      </div>
      {!result.grid_monotone && (
        <Notice tone="warning" title="Pass/fail was not monotone">
          Some larger drawdowns passed after a smaller one failed, so the boundary is the first failing point found, not a
          guaranteed exact threshold.
        </Notice>
      )}
      <Card title="Method">
        <p className="text-sm text-slate-700">{result.method}</p>
        <p className="mt-1 text-xs text-slate-500">
          Engine {result.engine_version} · {formatDateTime(result.created_at)}
        </p>
      </Card>
      <Card title="Search grid">
        <GridChart result={result} currency={currency} />
      </Card>
      <Card title="Binding constraints at the boundary">
        {result.binding_constraints.length ? (
          <ul className="flex flex-wrap gap-2">
            {result.binding_constraints.map((b) => (
              <li key={b}>
                <Badge tone="info">{b}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-600">None recorded.</p>
        )}
      </Card>
      <Card title="Attribution: shortfall with and without each rule">
        {result.attribution.length ? (
          <DictTable rows={result.attribution} currency={currency} label="Attribution" />
        ) : (
          <p className="text-sm text-slate-600">No attribution available.</p>
        )}
      </Card>
      <Card title="Key events up to the first failure">
        {result.key_events.length ? (
          <DictTable rows={result.key_events} currency={currency} label="Key events" />
        ) : (
          <p className="text-sm text-slate-600">No key events available.</p>
        )}
      </Card>
    </div>
  );
}

const PARAMS: Array<{ key: keyof StressRequest; label: string; hint: string }> = [
  { key: "max_drawdown", label: "Maximum drawdown to search (%)", hint: "Upper end of the equity drawdown search." },
  { key: "step", label: "Grid step (%)", hint: "Spacing of the grid search." },
  { key: "tolerance", label: "Bisection tolerance (%)", hint: "Precision of the boundary." },
];

export function StressView({
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
  const history = useApiQuery(async () => {
    const page = await endpoints.listStress(householdId, { limit: 100 });
    return page.items.filter((s) => s.scenario_id === scenarioId);
  }, [householdId, scenarioId]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useApiQuery(() => endpoints.getStress(selectedId as string), [selectedId], Boolean(selectedId));
  const [inputs, setInputs] = useState<Record<string, string>>({ max_drawdown: "", step: "", tolerance: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [runError, setRunError] = useState<unknown>(null);
  const [running, setRunning] = useState(false);
  const [latest, setLatest] = useState<StressOut | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    const body: StressRequest = {};
    const v: Record<string, string> = {};
    for (const p of PARAMS) {
      const s = inputs[p.key]?.trim();
      if (!s) continue;
      const n = Number(s);
      if (!Number.isFinite(n) || n <= 0) v[p.key] = "Enter a positive percentage.";
      else body[p.key] = Number((n / 100).toPrecision(12));
    }
    setErrors(v);
    setRunError(null);
    if (Object.keys(v).length) return;
    setRunning(true);
    try {
      const result = await endpoints.runStress(scenarioId, body);
      setLatest(result);
      setSelectedId(null);
      toast.success("Reverse stress search complete");
      void history.reload();
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setRunError(err);
    } finally {
      setRunning(false);
    }
  };

  const shown = selectedId ? selected.data : (latest ?? history.data?.[0] ?? null);

  return (
    <div className="space-y-5">
      <div>
        <Link href={`/households/${householdId}/scenarios/${scenarioId}`} className="text-xs text-slate-600 hover:underline">
          ← Scenario
        </Link>
        <h2 className="mt-1 text-lg font-semibold text-slate-900">Reverse stress test</h2>
        <p className="text-sm text-slate-600">
          Finds the smallest equity drawdown at which this scenario first runs out of cash under the contract-aware model.
        </p>
      </div>

      {canEdit && (
        <Card title="Run a search">
          <form onSubmit={run} noValidate className="space-y-3">
            {runError ? <ErrorState error={runError} /> : null}
            <div className="grid gap-3 sm:grid-cols-3">
              {PARAMS.map((p) => (
                <TextField
                  key={p.key}
                  label={p.label}
                  inputMode="decimal"
                  placeholder="API default"
                  value={inputs[p.key] ?? ""}
                  error={errors[p.key]}
                  hint={`${p.hint} Leave blank to use the API default.`}
                  onChange={(e) => setInputs((s) => ({ ...s, [p.key]: e.target.value }))}
                />
              ))}
            </div>
            <Button type="submit" variant="accent" loading={running}>
              Run reverse stress
            </Button>
          </form>
        </Card>
      )}

      {selectedId && selected.loading && !selected.data ? (
        <LoadingBlock rows={4} />
      ) : selectedId && selected.error ? (
        <ErrorState error={selected.error} onRetry={() => void selected.reload()} />
      ) : shown ? (
        <StressResult result={shown} currency={currency} />
      ) : history.loading ? (
        <LoadingBlock rows={3} />
      ) : (
        <EmptyState title="No reverse stress results yet">Run a search to see where this scenario breaks.</EmptyState>
      )}

      <Card title="History for this scenario">
        {history.error ? (
          <ErrorState error={history.error} onRetry={() => void history.reload()} />
        ) : !history.data || history.data.length === 0 ? (
          <p className="text-sm text-slate-600">No previous results.</p>
        ) : (
          <TableWrap label="Reverse stress history">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Run at</th>
                  <th className={th}>Boundary</th>
                  <th className={th}>First failure month</th>
                  <th className={th}>
                    <span className="sr-only">View</span>
                  </th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {history.data.map((h) => (
                  <tr key={h.id}>
                    <td className={td}>{formatDateTime(h.created_at)}</td>
                    <td className={td}>{h.found ? formatPercent(h.boundary_drawdown, 2) : "Not reached"}</td>
                    <td className={td}>{h.first_shortfall_month ?? EMPTY}</td>
                    <td className={td}>
                      <Button size="sm" variant="ghost" aria-pressed={shown?.id === h.id} onClick={() => setSelectedId(h.id)}>
                        {shown?.id === h.id ? "Showing" : "View"}
                      </Button>
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
