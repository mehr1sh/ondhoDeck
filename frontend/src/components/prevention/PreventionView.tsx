"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
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
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { AssumptionBadge, RecommendationStatusBadge } from "@/components/badges";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, formatNumber, humanize, parseDecimal } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { CostAssumptionsIn, PreventionOut, PreventionRequest, RecommendationOut } from "@/lib/types";

type CostKey = keyof CostAssumptionsIn | "cash_buffer";

const COST_FIELDS: Array<{ key: CostKey; label: string; percent: boolean; hint: string }> = [
  { key: "sale_tax_drag", label: "Sale tax drag (%)", percent: true, hint: "Tax cost as a share of assets sold." },
  { key: "cash_drag", label: "Cash drag (%/yr)", percent: true, hint: "Return given up by holding extra cash." },
  { key: "reit_forgone_return", label: "REIT forgone return (%/yr)", percent: true, hint: "Return given up by redeeming REIT shares early." },
  { key: "withholding_time_value", label: "Withholding time value (%/yr)", percent: true, hint: "Cost of over-withholding tax on RSU vests." },
  { key: "discretionary_weight", label: "Discretionary spending weight", percent: false, hint: "Relative cost weight for cutting discretionary spending." },
  { key: "cash_buffer", label: "Cash buffer", percent: false, hint: "Minimum cash to keep in every month (reporting currency)." },
];

/** A cost is "assumed" when its basis is a heuristic or modelling assumption rather than an observed amount. */
export function isAssumedCost(basis: string): boolean {
  return /assum|heuristic|estimat|weight|proxy|drag|time value|forgone/i.test(basis);
}

function amountText(r: RecommendationOut, currency: string): string {
  const unit = (r.unit || "").toLowerCase();
  if (!unit || unit === "currency" || unit === "money" || unit === currency.toLowerCase() || unit.length === 3) {
    return formatMoney(r.amount, unit.length === 3 ? r.unit.toUpperCase() : currency);
  }
  if (unit === "fraction" || unit === "share") return `${formatNumber((parseDecimal(r.amount) ?? 0) * 100, 2)}%`;
  return `${formatNumber(r.amount, 2)} ${r.unit}`;
}

function RecommendationActions({
  rec,
  canEdit,
  onChanged,
  householdId,
}: {
  rec: RecommendationOut;
  canEdit: boolean;
  onChanged: (r: RecommendationOut | null) => void;
  householdId: string;
}) {
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = useState<"approved" | "rejected" | "apply" | null>(null);
  if (!canEdit) return <RecommendationStatusBadge status={rec.status} />;

  const decide = async (decision: "approved" | "rejected") => {
    setBusy(decision);
    try {
      const updated = await endpoints.decideRecommendation(rec.id, { decision });
      onChanged(updated && typeof updated === "object" && "id" in updated ? updated : null);
      toast.success(decision === "approved" ? "Recommendation approved" : "Recommendation rejected");
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setBusy(null);
    }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      const out = await endpoints.applyRecommendation(rec.id);
      toast.success("New scenario created", out.scenario.name);
      router.push(`/households/${householdId}/scenarios/${out.scenario.id}`);
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      <RecommendationStatusBadge status={rec.status} />
      {rec.status !== "approved" && (
        <Button size="sm" variant="secondary" onClick={() => decide("approved")} loading={busy === "approved"} disabled={busy !== null} aria-label={`Approve ${rec.name}`}>
          Approve
        </Button>
      )}
      {rec.status !== "rejected" && (
        <Button size="sm" variant="ghost" onClick={() => decide("rejected")} loading={busy === "rejected"} disabled={busy !== null} aria-label={`Reject ${rec.name}`}>
          Reject
        </Button>
      )}
      {rec.status === "approved" && (
        <Button size="sm" variant="accent" onClick={apply} loading={busy === "apply"} disabled={busy !== null}>
          Apply as new scenario
        </Button>
      )}
    </div>
  );
}

function CostCell({ rec, currency }: { rec: RecommendationOut; currency: string }) {
  return (
    <div className="text-right">
      <span className="tabular-nums">{formatMoney(rec.cost, currency)}</span>
      <div className="mt-0.5 flex flex-wrap justify-end gap-1">
        {isAssumedCost(rec.cost_basis) && (
          <Badge tone="warning" title={rec.cost_basis}>
            assumed cost
          </Badge>
        )}
      </div>
      {rec.cost_basis && <p className="mt-0.5 text-xs text-slate-500">{rec.cost_basis}</p>}
    </div>
  );
}

function PlanResult({
  plan,
  currency,
  canEdit,
  householdId,
  onRecChanged,
}: {
  plan: PreventionOut;
  currency: string;
  canEdit: boolean;
  householdId: string;
  onRecChanged: (r: RecommendationOut | null) => void;
}) {
  const combined = plan.recommendations.filter((r) => r.kind === "combined").sort((a, b) => a.rank - b.rank);
  const singles = plan.recommendations.filter((r) => r.kind === "single").sort((a, b) => a.rank - b.rank);
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Baseline first shortfall"
          value={plan.baseline_first_shortfall ? `Month ${plan.baseline_first_shortfall}` : "None"}
          tone={plan.baseline_first_shortfall ? "danger" : "success"}
        />
        <Stat label="Baseline peak shortfall" value={formatMoney(plan.baseline_peak_shortfall, currency)} />
        <Stat label="Cost of doing nothing" value={formatMoney(plan.forced_liquidation_cost, currency)} hint={plan.forced_liquidation_note} tone="danger" />
        <Stat
          label="Combined plan cost"
          value={formatMoney(plan.combined_cost, currency)}
          hint={`Min cash after: ${formatMoney(plan.combined_min_cash, currency)} · first shortfall: ${plan.combined_first_shortfall ? `month ${plan.combined_first_shortfall}` : "none"}`}
        />
      </div>

      <Card
        title="Combined plan"
        actions={
          <div className="flex flex-wrap gap-1">
            {plan.combined_verified ? (
              <Badge tone="success" title="Re-simulated with all actions applied">Verified by re-simulation</Badge>
            ) : (
              <Badge tone="danger" title="The combination was not confirmed by re-simulation">Not verified</Badge>
            )}
            <Badge title="How the combination was produced">Source: {humanize(plan.combined_source)}</Badge>
            <Badge title="Optimiser status">LP status: {plan.lp_status}</Badge>
          </div>
        }
      >
        {combined.length === 0 ? (
          <p className="text-sm text-slate-600">The planner did not return a combined recommendation.</p>
        ) : (
          <RecTable recs={combined} currency={currency} canEdit={canEdit} householdId={householdId} onRecChanged={onRecChanged} />
        )}
      </Card>

      <Card title="Single actions, ranked by the planner">
        <p className="mb-3 text-xs text-slate-600">
          Rankings are computed by the SlipSlopes engine from the cost assumptions above. Costs marked “assumed cost” rely
          on those assumptions rather than observed prices.
        </p>
        {singles.length === 0 ? (
          <p className="text-sm text-slate-600">No single actions returned.</p>
        ) : (
          <RecTable recs={singles} currency={currency} canEdit={canEdit} householdId={householdId} onRecChanged={onRecChanged} />
        )}
      </Card>

      <Card title="Method">
        <p className="text-sm text-slate-700">{plan.method}</p>
        <p className="mt-1 text-xs text-slate-500">
          Engine {plan.engine_version} · {formatDateTime(plan.created_at)}
        </p>
      </Card>
    </div>
  );
}

function RecTable({
  recs,
  currency,
  canEdit,
  householdId,
  onRecChanged,
}: {
  recs: RecommendationOut[];
  currency: string;
  canEdit: boolean;
  householdId: string;
  onRecChanged: (r: RecommendationOut | null) => void;
}) {
  return (
    <TableWrap label="Recommendations">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={thNum}>Rank</th>
            <th className={th}>Action</th>
            <th className={thNum}>Amount</th>
            <th className={thNum}>Cost</th>
            <th className={thNum}>Liquidity benefit</th>
            <th className={thNum}>Min cash after</th>
            <th className={th}>New first shortfall</th>
            <th className={th}>Feasible alone</th>
            <th className={th}>Constraints</th>
            <th className={th}>Decision</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {recs.map((r) => (
            <tr key={r.id}>
              <td className={tdNum}>{r.rank}</td>
              <td className={td}>
                <span className="font-medium">{r.name}</span>
                <span className="block text-xs text-slate-500">{humanize(r.lever)}</span>
              </td>
              <td className={tdNum}>{amountText(r, currency)}</td>
              <td className={cx(td, "min-w-36")}>
                <CostCell rec={r} currency={currency} />
              </td>
              <td className={tdNum}>{r.liquidity_benefit !== null ? formatMoney(r.liquidity_benefit, currency) : EMPTY}</td>
              <td className={tdNum}>{r.min_cash_after !== null ? formatMoney(r.min_cash_after, currency) : EMPTY}</td>
              <td className={td}>{r.first_shortfall_after ? `Month ${r.first_shortfall_after}` : "None"}</td>
              <td className={td}>
                {r.feasible_alone === null ? EMPTY : r.feasible_alone ? <Badge tone="success">Yes</Badge> : <Badge tone="warning">No</Badge>}
              </td>
              <td className={cx(td, "min-w-48 text-xs")}>{r.constraints_note || EMPTY}</td>
              <td className={cx(td, "min-w-52")}>
                <RecommendationActions rec={r} canEdit={canEdit} householdId={householdId} onChanged={onRecChanged} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

export function PreventionView({
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
    const page = await endpoints.listPrevention(householdId, { limit: 100 });
    return page.items.filter((p) => p.scenario_id === scenarioId);
  }, [householdId, scenarioId]);
  const [plan, setPlan] = useState<PreventionOut | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [prefilled, setPrefilled] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [runError, setRunError] = useState<unknown>(null);
  const [running, setRunning] = useState(false);

  // Show the most recent plan and prefill its cost assumptions.
  useEffect(() => {
    if (prefilled || !history.data) return;
    const latest = history.data[0];
    if (latest) {
      setPlan((p) => p ?? latest);
      const next: Record<string, string> = {};
      for (const f of COST_FIELDS) {
        const v = latest.cost_assumptions[f.key];
        if (typeof v === "number") next[f.key] = String(f.percent ? Number((v * 100).toPrecision(12)) : v);
      }
      setInputs((s) => ({ ...next, ...s }));
    }
    setPrefilled(true);
  }, [history.data, prefilled]);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    const v: Record<string, string> = {};
    const costs: CostAssumptionsIn = {};
    let cashBuffer: number | undefined;
    for (const f of COST_FIELDS) {
      const s = inputs[f.key]?.trim();
      if (!s) continue;
      const n = Number(s.replace(/,/g, ""));
      if (!Number.isFinite(n) || n < 0) {
        v[f.key] = "Enter a non-negative number.";
        continue;
      }
      const value = f.percent ? Number((n / 100).toPrecision(12)) : n;
      if (f.key === "cash_buffer") cashBuffer = value;
      else costs[f.key] = value;
    }
    setErrors(v);
    setRunError(null);
    if (Object.keys(v).length) return;
    const body: PreventionRequest = { costs };
    if (cashBuffer !== undefined) body.cash_buffer = cashBuffer;
    setRunning(true);
    try {
      const result = await endpoints.runPrevention(scenarioId, body);
      setPlan(result);
      toast.success("Prevention plan computed");
      void history.reload();
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) {
        const fe = err.fieldErrors;
        const mapped: Record<string, string> = {};
        for (const [k, msg] of Object.entries(fe)) mapped[k.replace(/^costs\./, "")] = msg;
        setErrors(mapped);
      }
      setRunError(err);
    } finally {
      setRunning(false);
    }
  };

  const onRecChanged = async (updated: RecommendationOut | null) => {
    if (!plan) return;
    if (updated) {
      setPlan({ ...plan, recommendations: plan.recommendations.map((r) => (r.id === updated.id ? updated : r)) });
    } else {
      try {
        setPlan(await endpoints.getPrevention(plan.id));
      } catch {
        /* keep current view */
      }
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <Link href={`/households/${householdId}/scenarios/${scenarioId}`} className="text-xs text-slate-600 hover:underline">
          ← Scenario
        </Link>
        <h2 className="mt-1 text-lg font-semibold text-slate-900">Prevention planner</h2>
        <p className="text-sm text-slate-600">
          Ranks actions that could prevent the projected shortfall and proposes a combination verified by re-simulation.
          Nothing changes until you approve an action and apply it as a new scenario.
        </p>
      </div>

      {canEdit && (
        <Card title={<span className="flex items-center gap-2">Cost assumptions <AssumptionBadge /></span>}>
          <form onSubmit={run} noValidate className="space-y-3">
            {runError ? <ErrorState error={runError} /> : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {COST_FIELDS.map((f) => (
                <TextField
                  key={f.key}
                  label={f.label}
                  badge={<AssumptionBadge />}
                  inputMode="decimal"
                  placeholder="API default"
                  value={inputs[f.key] ?? ""}
                  error={errors[f.key]}
                  hint={`${f.hint} Blank uses the API default.`}
                  onChange={(e) => setInputs((s) => ({ ...s, [f.key]: e.target.value }))}
                />
              ))}
            </div>
            <Button type="submit" variant="accent" loading={running}>
              Compute prevention plan
            </Button>
          </form>
        </Card>
      )}

      {plan ? (
        <>
          <p className="text-xs text-slate-500">Showing plan from {formatDateTime(plan.created_at)}.</p>
          <PlanResult plan={plan} currency={currency} canEdit={canEdit} householdId={householdId} onRecChanged={onRecChanged} />
        </>
      ) : history.loading ? (
        <LoadingBlock rows={3} />
      ) : history.error ? (
        <ErrorState error={history.error} onRetry={() => void history.reload()} />
      ) : (
        <EmptyState title="No prevention plans yet">Compute a plan to see ranked actions for this scenario.</EmptyState>
      )}

      {history.data && history.data.length > 1 && (
        <Card title="Previous plans">
          <ul className="divide-y divide-slate-100 text-sm">
            {history.data.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  {formatDateTime(p.created_at)} · cost {formatMoney(p.combined_cost, currency)}
                </span>
                <Button size="sm" variant="ghost" aria-pressed={plan?.id === p.id} onClick={() => setPlan(p)}>
                  {plan?.id === p.id ? "Showing" : "View"}
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {!canEdit && <Notice>You have view-only access; computing plans and approving actions is disabled.</Notice>}
    </div>
  );
}
