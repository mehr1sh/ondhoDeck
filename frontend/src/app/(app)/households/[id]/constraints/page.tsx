"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import {
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
import { ConfidenceBadge, QuoteVerifiedBadge, ReviewStatusBadge, SourceTypeBadge } from "@/components/badges";
import { useHousehold } from "@/components/household/HouseholdContext";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, humanize } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import { ConstraintValue } from "@/components/constraints/shared";
import { REVIEW_STATUSES, type ReviewStatus } from "@/lib/types";

const LIMIT = 50;

export default function ConstraintsPage() {
  const { household } = useHousehold();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const documentId = params?.get("document_id") ?? "";
  const reviewStatus = (params?.get("review_status") ?? "") as ReviewStatus | "";
  const [offset, setOffset] = useState(0);

  const docs = useApiQuery(() => endpoints.listDocuments(household.id, { limit: 100 }), [household.id]);
  const q = useApiQuery(
    () =>
      endpoints.listConstraints(household.id, {
        limit: LIMIT,
        offset,
        document_id: documentId || undefined,
        review_status: reviewStatus || undefined,
      }),
    [household.id, documentId, reviewStatus, offset],
  );

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params?.toString() ?? "");
    if (value) next.set(key, value);
    else next.delete(key);
    setOffset(0);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname ?? "");
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">Contract Explorer</h2>
        <p className="text-sm text-slate-600">
          Constraints extracted from your documents, each with its cited evidence. Approve or edit them before they are
          used in simulations.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:max-w-2xl">
        <SelectField
          label="Document"
          value={documentId}
          onChange={(e) => setFilter("document_id", e.target.value)}
          options={[
            { value: "", label: "All documents" },
            ...(docs.data?.items ?? []).map((d) => ({ value: d.id, label: d.original_filename })),
          ]}
        />
        <SelectField
          label="Review status"
          value={reviewStatus}
          onChange={(e) => setFilter("review_status", e.target.value)}
          options={[{ value: "", label: "All statuses" }, ...REVIEW_STATUSES.map((s) => ({ value: s, label: humanize(s) }))]}
        />
      </div>
      {q.loading && !q.data ? (
        <LoadingBlock rows={5} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : !q.data || q.data.items.length === 0 ? (
        <EmptyState title="No constraints match">
          {documentId || reviewStatus ? "Try clearing the filters." : "Upload and process documents to extract constraints."}
        </EmptyState>
      ) : (
        <>
          <TableWrap label="Constraints">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Constraint</th>
                  <th className={th}>Value</th>
                  <th className={th}>Document</th>
                  <th className={thNum}>Page</th>
                  <th className={th}>Source</th>
                  <th className={th}>Evidence</th>
                  <th className={th}>Confidence</th>
                  <th className={th}>Review</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {q.data.items.map((c) => (
                  <tr key={c.id}>
                    <td className={td}>
                      <Link href={`/households/${household.id}/constraints/${c.id}`} className="font-medium underline-offset-2 hover:underline">
                        {humanize(c.constraint_type)}
                      </Link>
                      <span className="block text-xs text-slate-600">{c.asset_key}</span>
                      <span className="block max-w-xs text-xs text-slate-700">{c.description}</span>
                    </td>
                    <td className={td}>
                      <ConstraintValue c={c} />
                    </td>
                    <td className={td}>
                      <span className="break-all">{c.document_name || EMPTY}</span>
                    </td>
                    <td className={tdNum}>{c.pdf_page}</td>
                    <td className={td}>
                      <SourceTypeBadge sourceType={c.source_type} />
                    </td>
                    <td className={td}>
                      <QuoteVerifiedBadge verified={c.quote_verified} />
                    </td>
                    <td className={td}>
                      <ConfidenceBadge confidence={c.confidence} />
                    </td>
                    <td className={td}>
                      <ReviewStatusBadge status={c.review_status} />
                    </td>
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
