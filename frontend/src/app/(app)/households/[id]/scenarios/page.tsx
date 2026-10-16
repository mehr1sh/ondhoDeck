"use client";

import Link from "next/link";
import { EmptyState, ErrorState, LinkButton, LoadingBlock, TableWrap, tableClass, tbodyClass, td, th } from "@/components/ui";
import { useHousehold } from "@/components/household/HouseholdContext";
import { itemsOf } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

export default function ScenariosPage() {
  const { household, canEdit } = useHousehold();
  const q = useApiQuery(async () => itemsOf(await endpoints.listScenarios(household.id, { limit: 100 })), [household.id]);
  const base = `/households/${household.id}/scenarios`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-[1.35rem] text-ink">Scenarios</h2>
          <p className="text-sm text-slate-600">
            A scenario is a set of market and behaviour assumptions. Run it to compare a naive liquidity view with the
            contract-aware view.
          </p>
        </div>
        {canEdit && (
          <LinkButton href={`${base}/new`} variant="primary">
            New scenario
          </LinkButton>
        )}
      </div>
      {q.loading && !q.data ? (
        <LoadingBlock />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : !q.data || q.data.length === 0 ? (
        <EmptyState
          title="No scenarios yet"
          action={canEdit ? <LinkButton href={`${base}/new`} variant="primary">Create a scenario</LinkButton> : undefined}
        >
          New scenarios start from the default assumptions provided by the API; you can adjust each one.
        </EmptyState>
      ) : (
        <TableWrap label="Scenarios">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Description</th>
                <th className={th}>Updated</th>
                <th className={th}>Analyses</th>
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {q.data.map((s) => (
                <tr key={s.id}>
                  <td className={td}>
                    <Link href={`${base}/${s.id}`} className="font-medium underline-offset-2 hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td className={td}>{s.description || "—"}</td>
                  <td className={td}>{formatDateTime(s.updated_at)}</td>
                  <td className={td}>
                    <div className="flex flex-wrap gap-2">
                      <Link href={`${base}/${s.id}/stress`} className="text-sm underline">
                        Reverse stress
                      </Link>
                      <Link href={`${base}/${s.id}/prevention`} className="text-sm underline">
                        Prevention
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}
