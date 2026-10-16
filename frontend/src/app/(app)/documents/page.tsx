"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  EmptyState,
  ErrorState,
  FilterInput,
  FilterSelect,
  LinkButton,
  LoadingBlock,
  Notice,
  PageHeader,
  Pagination,
  SortTh,
  SyntheticBadge,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  useSortedRows,
} from "@/components/ui";
import { DocumentStatusBadge } from "@/components/badges";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, humanize } from "@/lib/format";
import { useApiQuery, usePolling } from "@/lib/hooks";
import { ACTIVE_DOC_STATUSES } from "@/lib/upload";
import type { DocumentOut } from "@/lib/types";

const LIMIT = 100;
const STATUS_OPTIONS = ["pending_upload", "uploaded", "queued", "processing", "extracted", "failed"];

export default function DocumentsIndexPage() {
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [household, setHousehold] = useState("");
  const [search, setSearch] = useState("");
  const docs = useApiQuery(() => endpoints.myDocuments({ limit: LIMIT, offset }), [offset]);
  const households = useApiQuery(() => endpoints.listHouseholds({ limit: 100 }), []);
  const names = useMemo(
    () => new Map((households.data?.items ?? []).map((h) => [h.id, h.name] as const)),
    [households.data],
  );
  const anyActive = Boolean(docs.data?.items.some((d) => ACTIVE_DOC_STATUSES.has(d.status)));
  usePolling(() => void docs.reload(), 5000, anyActive);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (docs.data?.items ?? []).filter(
      (d) =>
        (!status || d.status === status) &&
        (!household || d.household_id === household) &&
        (!s || d.original_filename.toLowerCase().includes(s)),
    );
  }, [docs.data, status, household, search]);

  const { rows, sort, toggle } = useSortedRows<DocumentOut, "file" | "household" | "status" | "terms" | "uploaded">(
    filtered,
    {
      file: (d) => d.original_filename,
      household: (d) => (d.household_id ? names.get(d.household_id) : null),
      status: (d) => d.status,
      terms: (d) => d.constraint_count ?? null,
      uploaded: (d) => d.created_at,
    },
    { key: "uploaded", dir: "desc" },
  );

  const householdOptions = [...new Set((docs.data?.items ?? []).map((d) => d.household_id).filter(Boolean) as string[])];
  const filtering = Boolean(status || household || search.trim());

  return (
    <div className="space-y-5">
      <PageHeader
        title="Documents"
        description="Private household agreements across every household you can access, with their processing status."
        actions={
          <LinkButton href="/households" variant="primary">
            Upload from a household
          </LinkButton>
        }
      />
      <Notice>
        Household documents are private agreements and are uploaded from a household&apos;s Documents tab. Public offering
        documents (prospectuses, supplements, SAIs) belong in the{" "}
        <Link href="/funds" className="font-medium underline">
          Fund Library
        </Link>
        , where reviewers approve their terms once for every linked holding.
      </Notice>
      {docs.loading && !docs.data ? (
        <LoadingBlock rows={4} />
      ) : docs.error || !docs.data ? (
        <ErrorState error={docs.error} onRetry={() => void docs.reload()} />
      ) : docs.data.items.length === 0 ? (
        <EmptyState
          title="No household documents yet"
          action={
            <LinkButton href="/households" variant="primary">
              Choose a household
            </LinkButton>
          }
        >
          Open a household and upload an agreement from its Documents tab.
        </EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <FilterInput label="Search file name" value={search} onChange={setSearch} />
            <FilterSelect
              label="Status"
              value={status}
              onChange={setStatus}
              options={[{ value: "", label: "All statuses" }, ...STATUS_OPTIONS.map((s) => ({ value: s, label: humanize(s) }))]}
            />
            <FilterSelect
              label="Household"
              value={household}
              onChange={setHousehold}
              options={[
                { value: "", label: "All households" },
                ...householdOptions.map((id) => ({ value: id, label: names.get(id) ?? "Household" })),
              ]}
            />
          </div>
          {docs.data.total > docs.data.items.length && (
            <p className="small-print">
              Filters and sorting apply to the {docs.data.items.length} documents on this page of {docs.data.total}.
            </p>
          )}
          {rows.length === 0 ? (
            <p className="text-sm text-ink-3">{filtering ? "No documents match the filters." : "No documents."}</p>
          ) : (
            <TableWrap label="Household documents">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <SortTh label="File" sortKey="file" sort={sort} onSort={toggle} />
                    <SortTh label="Household" sortKey="household" sort={sort} onSort={toggle} />
                    <th className={th}>Category</th>
                    <SortTh label="Status" sortKey="status" sort={sort} onSort={toggle} />
                    <SortTh label="Terms" sortKey="terms" sort={sort} onSort={toggle} numeric />
                    <SortTh label="Uploaded" sortKey="uploaded" sort={sort} onSort={toggle} />
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {rows.map((d) => (
                    <tr key={d.id}>
                      <td className={td}>
                        {d.household_id ? (
                          <Link
                            href={`/households/${d.household_id}/documents/${d.id}`}
                            className="break-all text-accent-ink underline-offset-2 hover:underline"
                          >
                            {d.original_filename}
                          </Link>
                        ) : (
                          <span className="break-all">{d.original_filename}</span>
                        )}{" "}
                        {d.is_demo_fixture && <SyntheticBadge />}
                      </td>
                      <td className={td}>
                        {d.household_id ? (
                          <Link href={`/households/${d.household_id}`} className="underline-offset-2 hover:underline">
                            {names.get(d.household_id) ?? "Household"}
                          </Link>
                        ) : (
                          EMPTY
                        )}
                      </td>
                      <td className={td}>{humanize(d.category)}</td>
                      <td className={td}>
                        <DocumentStatusBadge status={d.status} />
                        {d.status === "failed" && (
                          <span className="mt-1 block max-w-xs text-xs text-risk">{d.error_message || "Processing failed."}</span>
                        )}
                      </td>
                      <td className={tdNum}>{d.constraint_count ?? EMPTY}</td>
                      <td className={td}>{formatDateTime(d.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          <Pagination total={docs.data.total} limit={docs.data.limit || LIMIT} offset={docs.data.offset} onChange={setOffset} />
        </>
      )}
    </div>
  );
}
