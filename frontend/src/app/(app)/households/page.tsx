"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  EmptyState,
  ErrorState,
  LinkButton,
  LoadingBlock,
  PageHeader,
  Pagination,
  SyntheticBadge,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { formatDateTime, MONTH_NAMES } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

const LIMIT = 20;

export default function HouseholdsPage() {
  const [offset, setOffset] = useState(0);
  const q = useApiQuery(() => endpoints.listHouseholds({ limit: LIMIT, offset }), [offset]);

  return (
    <div>
      <PageHeader
        title="Households"
        description="Each household holds its financial profile, private agreements, liquidity scenarios and reports."
        actions={
          <LinkButton href="/households/new" variant="primary">
            Create household
          </LinkButton>
        }
      />
      {q.loading && !q.data ? (
        <LoadingBlock />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : !q.data || q.data.items.length === 0 ? (
        <EmptyState
          title="No households yet"
          action={
            <>
              <LinkButton href="/households/new" variant="primary">
                Create household
              </LinkButton>
              <LinkButton href="/">Create a demo household from Overview</LinkButton>
            </>
          }
        >
          Create a household to record assets, obligations and private agreements. A demo household with synthetic data
          is available from the Overview.
        </EmptyState>
      ) : (
        <>
          <TableWrap label="Households">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Name</th>
                  <th className={th}>Currency</th>
                  <th className={th}>Start month</th>
                  <th className={th}>Your role</th>
                  <th className={th}>Updated</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {q.data.items.map((h) => (
                  <tr key={h.id}>
                    <td className={td}>
                      <Link href={`/households/${h.id}`} className="font-medium underline-offset-2 hover:underline">
                        {h.name}
                      </Link>{" "}
                      {h.is_demo && <SyntheticBadge />}
                    </td>
                    <td className={td}>{h.reporting_currency}</td>
                    <td className={td}>{MONTH_NAMES[h.start_calendar_month - 1] ?? h.start_calendar_month}</td>
                    <td className={td}>
                      <Badge>{h.role}</Badge>
                    </td>
                    <td className={td}>{formatDateTime(h.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <Pagination total={q.data.total} limit={q.data.limit || LIMIT} offset={q.data.offset} onChange={setOffset} />
        </>
      )}
    </div>
  );
}
