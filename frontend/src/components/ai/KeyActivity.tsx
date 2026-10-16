"use client";

import { useState } from "react";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Pagination,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { formatDateTime, humanize } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";

const LIMIT = 20;

/** The signed-in user's own API key events. Event details never contain key material. */
export function KeyActivity() {
  const [offset, setOffset] = useState(0);
  const events = useApiQuery(() => endpoints.aiProviderEvents({ limit: LIMIT, offset }), [offset]);
  return (
    <Card
      title="Key activity"
      actions={
        <Button variant="secondary" onClick={() => void events.reload()}>
          Refresh
        </Button>
      }
    >
      {events.loading && !events.data ? (
        <LoadingBlock />
      ) : events.error ? (
        <ErrorState error={events.error} onRetry={() => void events.reload()} />
      ) : !events.data || events.data.items.length === 0 ? (
        <EmptyState title="No key activity yet" />
      ) : (
        <>
          <TableWrap label="API key events">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>When</th>
                  <th className={th}>Action</th>
                  <th className={th}>Provider</th>
                  <th className={th}>Result / fields</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {events.data.items.map((e) => {
                  const d = e.details as Record<string, unknown>;
                  const extra = d.result ?? (Array.isArray(d.fields) ? d.fields.join(", ") : d.model);
                  return (
                    <tr key={e.id}>
                      <td className={td}>{formatDateTime(e.created_at)}</td>
                      <td className={td}>{humanize(e.action.replace("ai_credential.", "key "))}</td>
                      <td className={td}>{String(d.provider ?? "—")}</td>
                      <td className={td}>{extra ? humanize(String(extra)) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          <Pagination total={events.data.total} limit={events.data.limit || LIMIT} offset={events.data.offset} onChange={setOffset} />
        </>
      )}
    </Card>
  );
}
