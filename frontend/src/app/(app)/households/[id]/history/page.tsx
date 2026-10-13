"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Pagination,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { useHousehold } from "@/components/household/HouseholdContext";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

const LIMIT = 20;

export default function HistoryPage() {
  const { household } = useHousehold();
  const hid = household.id;
  const ccy = household.reporting_currency;
  const [runOffset, setRunOffset] = useState(0);
  const [stressOffset, setStressOffset] = useState(0);
  const [planOffset, setPlanOffset] = useState(0);
  const runs = useApiQuery(() => endpoints.listRuns(hid, { limit: LIMIT, offset: runOffset }), [hid, runOffset]);
  const stress = useApiQuery(() => endpoints.listStress(hid, { limit: LIMIT, offset: stressOffset }), [hid, stressOffset]);
  const plans = useApiQuery(() => endpoints.listPrevention(hid, { limit: LIMIT, offset: planOffset }), [hid, planOffset]);
  const sc = (sid: string) => `/households/${hid}/scenarios/${sid}`;

  return (
    <div className="space-y-5">
      <Card title="Simulation runs">
        {runs.loading && !runs.data ? (
          <LoadingBlock />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={() => void runs.reload()} />
        ) : !runs.data || runs.data.items.length === 0 ? (
          <EmptyState title="No runs yet">Run a scenario to see results here.</EmptyState>
        ) : (
          <>
            <TableWrap label="Simulation runs">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>Run</th>
                    <th className={th}>Scenario</th>
                    <th className={th}>Contract-aware shortfall</th>
                    <th className={th}>Naive shortfall</th>
                    <th className={thNum}>Min cash (aware)</th>
                    <th className={thNum}>Warnings</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {runs.data.items.map((r) => (
                    <tr key={r.id}>
                      <td className={td}>
                        <Link href={`/households/${hid}/runs/${r.id}`} className="underline">
                          {formatDateTime(r.created_at)}
                        </Link>
                      </td>
                      <td className={td}>
                        <Link href={sc(r.scenario_id)} className="hover:underline">
                          {r.scenario_name || "Scenario"}
                        </Link>
                      </td>
                      <td className={td}>
                        {r.aware_summary.first_shortfall_month != null ? `Month ${r.aware_summary.first_shortfall_month}` : "None"}
                      </td>
                      <td className={td}>
                        {r.naive_summary.first_shortfall_month != null ? `Month ${r.naive_summary.first_shortfall_month}` : "None"}
                      </td>
                      <td className={tdNum}>{formatMoney(r.aware_summary.min_cash, r.reporting_currency)}</td>
                      <td className={tdNum}>{r.warnings.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pagination total={runs.data.total} limit={runs.data.limit || LIMIT} offset={runs.data.offset} onChange={setRunOffset} />
          </>
        )}
      </Card>

      <Card title="Reverse stress results">
        {stress.loading && !stress.data ? (
          <LoadingBlock />
        ) : stress.error ? (
          <ErrorState error={stress.error} onRetry={() => void stress.reload()} />
        ) : !stress.data || stress.data.items.length === 0 ? (
          <p className="text-sm text-slate-600">No reverse stress results yet.</p>
        ) : (
          <>
            <TableWrap label="Reverse stress results">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>When</th>
                    <th className={th}>Boundary drawdown</th>
                    <th className={th}>First failure month</th>
                    <th className={thNum}>Deficit</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {stress.data.items.map((s) => (
                    <tr key={s.id}>
                      <td className={td}>
                        <Link href={`${sc(s.scenario_id)}/stress`} className="underline">
                          {formatDateTime(s.created_at)}
                        </Link>
                      </td>
                      <td className={td}>{s.found ? formatPercent(s.boundary_drawdown, 2) : "Not reached"}</td>
                      <td className={td}>{s.first_shortfall_month ?? EMPTY}</td>
                      <td className={tdNum}>{formatMoney(s.shortfall_amount, ccy)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pagination total={stress.data.total} limit={stress.data.limit || LIMIT} offset={stress.data.offset} onChange={setStressOffset} />
          </>
        )}
      </Card>

      <Card title="Prevention plans">
        {plans.loading && !plans.data ? (
          <LoadingBlock />
        ) : plans.error ? (
          <ErrorState error={plans.error} onRetry={() => void plans.reload()} />
        ) : !plans.data || plans.data.items.length === 0 ? (
          <p className="text-sm text-slate-600">No prevention plans yet.</p>
        ) : (
          <>
            <TableWrap label="Prevention plans">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>When</th>
                    <th className={th}>Baseline first shortfall</th>
                    <th className={thNum}>Cost of doing nothing</th>
                    <th className={thNum}>Combined plan cost</th>
                    <th className={th}>Verified</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {plans.data.items.map((p) => (
                    <tr key={p.id}>
                      <td className={td}>
                        <Link href={`${sc(p.scenario_id)}/prevention`} className="underline">
                          {formatDateTime(p.created_at)}
                        </Link>
                      </td>
                      <td className={td}>{p.baseline_first_shortfall ? `Month ${p.baseline_first_shortfall}` : "None"}</td>
                      <td className={tdNum}>{formatMoney(p.forced_liquidation_cost, ccy)}</td>
                      <td className={tdNum}>{formatMoney(p.combined_cost, ccy)}</td>
                      <td className={td}>{p.combined_verified ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pagination total={plans.data.total} limit={plans.data.limit || LIMIT} offset={plans.data.offset} onChange={setPlanOffset} />
          </>
        )}
      </Card>
    </div>
  );
}
