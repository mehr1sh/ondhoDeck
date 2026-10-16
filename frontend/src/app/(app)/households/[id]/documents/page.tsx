"use client";

import Link from "next/link";
import { useState } from "react";
import {
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  Pagination,
  SyntheticBadge,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { DocumentStatusBadge } from "@/components/badges";
import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { useHousehold } from "@/components/household/HouseholdContext";
import { extractionMethodLabel } from "@/lib/extraction";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatBytes, formatDateTime, humanize } from "@/lib/format";
import { useApiQuery, usePolling } from "@/lib/hooks";
import { ACTIVE_DOC_STATUSES } from "@/lib/upload";

const LIMIT = 25;

export default function DocumentsPage() {
  const { household, canEdit } = useHousehold();
  const [offset, setOffset] = useState(0);
  const q = useApiQuery(() => endpoints.listDocuments(household.id, { limit: LIMIT, offset }), [household.id, offset]);
  const anyActive = Boolean(q.data?.items.some((d) => ACTIVE_DOC_STATUSES.has(d.status)));
  usePolling(() => void q.reload(), 4000, anyActive);

  return (
    <div className="space-y-6">
      <Notice title="Private agreements only">
        Upload this household&apos;s own agreements here: securities-based line agreements, subscription agreements,
        capital-call notices, RSU grants. Public offering documents (prospectuses, supplements, SAIs) belong in the{" "}
        <Link href="/funds" className="font-medium underline">
          Fund Library
        </Link>
        , where their terms are reviewed once and apply to every linked holding.
      </Notice>
      {canEdit ? (
        <DocumentUploader householdId={household.id} onChanged={() => void q.reload()} />
      ) : (
        <Notice>You have view-only access; uploading is disabled.</Notice>
      )}
      <section aria-labelledby="library-title">
        <h2 id="library-title" className="font-display mb-3 border-b border-line pb-2 text-lg text-ink">
          Household agreements
        </h2>
        {q.loading && !q.data ? (
          <LoadingBlock />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.reload()} />
        ) : !q.data || q.data.items.length === 0 ? (
          <EmptyState title="No documents yet">
            Upload this household&apos;s private agreements (for example a securities-based line agreement, LPA or RSU
            grant) above to extract liquidity terms with cited evidence.
          </EmptyState>
        ) : (
          <>
            <TableWrap label="Documents">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>File</th>
                    <th className={th}>Category</th>
                    <th className={th}>Status</th>
                    <th className={thNum}>Pages</th>
                    <th className={thNum}>Constraints</th>
                    <th className={th}>Extraction method</th>
                    <th className={thNum}>Size</th>
                    <th className={th}>Uploaded</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {q.data.items.map((d) => (
                    <tr key={d.id}>
                      <td className={td}>
                        <Link href={`/households/${household.id}/documents/${d.id}`} className="font-medium underline-offset-2 hover:underline break-all">
                          {d.original_filename}
                        </Link>{" "}
                        {d.is_demo_fixture && <SyntheticBadge />}
                      </td>
                      <td className={td}>{humanize(d.category)}</td>
                      <td className={td}>
                        <DocumentStatusBadge status={d.status} />
                        {d.latest_job && ACTIVE_DOC_STATUSES.has(d.status) && (
                          <span className="ml-1 text-xs text-slate-600 tabular-nums">{d.latest_job.progress}%</span>
                        )}
                        {d.status === "failed" && (
                          <span className="mt-1 block max-w-xs text-xs text-risk">
                            {d.error_message || "Processing failed."}{" "}
                            <Link href={`/households/${household.id}/documents/${d.id}`} className="underline">
                              Open to retry
                            </Link>
                          </span>
                        )}
                      </td>
                      <td className={tdNum}>{d.page_count ?? EMPTY}</td>
                      <td className={tdNum}>{d.constraint_count ?? 0}</td>
                      <td className={td}>{d.latest_job ? (extractionMethodLabel(d.latest_job) ?? EMPTY) : EMPTY}</td>
                      <td className={tdNum}>{formatBytes(d.size_bytes)}</td>
                      <td className={td}>{formatDateTime(d.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pagination total={q.data.total} limit={q.data.limit || LIMIT} offset={q.data.offset} onChange={setOffset} />
          </>
        )}
      </section>
    </div>
  );
}
