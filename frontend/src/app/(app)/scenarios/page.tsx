"use client";

import Link from "next/link";
import { EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, TableWrap, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatMoney } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

export default function ScenariosIndexPage() {
  const q = useApiQuery(() => endpoints.myScenarios(), []);
  const households = useApiQuery(() => endpoints.listHouseholds({ limit: 100 }), []);
  const currency = (hid: string) => households.data?.items.find((h) => h.id === hid)?.reporting_currency;
  return (
    <div>
      <PageHeader
        title="Liquidity Scenarios"
        description="Saved scenarios across your households with the result of each latest run. Create scenarios from a household's Scenarios tab."
        actions={
          <LinkButton href="/households" variant="primary">
            New scenario from a household
          </LinkButton>
        }
      />
      {q.loading && !q.data ? (
        <LoadingBlock rows={4} />
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : q.data.length === 0 ? (
        <EmptyState
          title="No scenarios yet"
          action={
            <LinkButton href="/households" variant="primary">
              Choose a household
            </LinkButton>
          }
        >
          Open a household and create a liquidity scenario from its Scenarios tab.
        </EmptyState>
      ) : (
        <TableWrap label="Scenarios">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={th}>Scenario</th>
                <th className={th}>Household</th>
                <th className={th}>Updated</th>
                <th className={th}>Latest run</th>
                <th className={th}>First shortfall</th>
                <th className={thNum}>Peak shortfall</th>
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {q.data.map((s) => (
                <tr key={s.id}>
                  <td className={td}>
                    <Link
                      href={`/households/${s.household_id}/scenarios/${s.id}`}
                      className="font-medium text-accent-ink underline-offset-2 hover:underline"
                    >
                      {s.name}
                    </Link>
                  </td>
                  <td className={td}>
                    <Link href={`/households/${s.household_id}`} className="underline-offset-2 hover:underline">
                      {s.household_name}
                    </Link>
                  </td>
                  <td className={td}>{formatDateTime(s.updated_at)}</td>
                  <td className={td}>
                    {s.latest_run_id ? (
                      <Link href={`/households/${s.household_id}/runs/${s.latest_run_id}`} className="underline-offset-2 hover:underline">
                        {formatDateTime(s.latest_run_at)}
                      </Link>
                    ) : (
                      <span className="text-ink-3">Not run</span>
                    )}
                  </td>
                  <td className={td}>
                    {!s.latest_run_id ? (
                      EMPTY
                    ) : s.latest_first_shortfall_month === null ? (
                      <span className="text-accent-ink">None in horizon</span>
                    ) : (
                      <span className="text-risk">Month {s.latest_first_shortfall_month}</span>
                    )}
                  </td>
                  <td className={tdNum}>{s.latest_peak_shortfall !== null ? formatMoney(s.latest_peak_shortfall, currency(s.household_id)) : EMPTY}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}
