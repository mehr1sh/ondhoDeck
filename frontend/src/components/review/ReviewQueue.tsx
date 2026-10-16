"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FilterInput,
  FilterSelect,
  LinkButton,
  LoadingBlock,
  PageHeader,
  SortTh,
  TableWrap,
  useSortedRows,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { AmbiguousBadge, QuoteVerifiedBadge, ValidationIssuesBadge } from "@/components/badges";
import { ConstraintValue } from "@/components/constraints/shared";
import { useReviewCount } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { ReviewItem } from "@/lib/types";

type Filter = "all" | "household" | "fund";
const QUOTE_MAX = 160;

function excerpt(q: string): string {
  return q.length > QUOTE_MAX ? `${q.slice(0, QUOTE_MAX).trimEnd()}…` : q;
}

function detailHref(item: ReviewItem): string {
  return item.owner_type === "fund"
    ? `/funds/${item.owner_id}`
    : `/households/${item.owner_id}/constraints/${item.constraint.id}`;
}

export function ReviewQueue() {
  const toast = useToast();
  const reviewCount = useReviewCount();
  const q = useApiQuery(() => endpoints.reviewQueue(500), []);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");

  const decide = async (item: ReviewItem, kind: "approve" | "reject") => {
    const c = item.constraint;
    setBusy(`${kind}-${c.id}`);
    try {
      const body = { expected_revision: c.revision };
      if (kind === "approve") await endpoints.approveConstraint(c.id, body);
      else await endpoints.rejectConstraint(c.id, body);
      toast.success(kind === "approve" ? "Term approved" : "Term rejected");
    } catch (e) {
      if (e instanceof ApiError && e.isConflict) {
        toast.error("This term was changed by someone else", "The queue has been refreshed; review it again.");
      } else {
        const d = describeError(e);
        toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      }
    } finally {
      setBusy(null);
      await q.reload();
      reviewCount.refresh();
    }
  };

  const data = q.data;
  const needle = search.trim().toLowerCase();
  const filtered = (data?.items ?? []).filter(
    (i) =>
      (filter === "all" || i.owner_type === filter) &&
      (!type || i.constraint.constraint_type === type) &&
      (!needle ||
        i.constraint.document_name.toLowerCase().includes(needle) ||
        i.owner_name.toLowerCase().includes(needle) ||
        i.constraint.evidence_quote.toLowerCase().includes(needle)),
  );
  const types = [...new Set((data?.items ?? []).map((i) => i.constraint.constraint_type))].sort();
  const { rows: items, sort, toggle } = useSortedRows<ReviewItem, "owner" | "type" | "document">(
    filtered,
    {
      owner: (i) => i.owner_name,
      type: (i) => humanize(i.constraint.constraint_type),
      document: (i) => `${i.constraint.document_name} ${String(i.constraint.pdf_page).padStart(5, "0")}`,
    },
    { key: "owner", dir: "asc" },
  );
  const tabs: Array<{ key: Filter; label: string; count: number | undefined }> = [
    { key: "all", label: "All", count: data?.total },
    { key: "household", label: "Household contracts", count: data?.household_items },
    { key: "fund", label: "Fund Library", count: data?.library_items },
  ];

  return (
    <div>
      <PageHeader
        title="Review Queue"
        description="Extracted terms waiting for a decision. Only approved terms are used in simulations. Household terms are reviewed by household editors; Fund Library terms by firm reviewers and admins."
      />
      <div role="tablist" aria-label="Filter by owner" className="mb-4 flex flex-wrap gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={filter === t.key}
            onClick={() => setFilter(t.key)}
            className={cx(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent",
              filter === t.key ? "border-accent text-ink" : "border-transparent text-ink-3 hover:text-ink",
            )}
          >
            {t.label}
            {t.count !== undefined && <span className="ml-1.5 tabular-nums text-ink-3">{t.count}</span>}
          </button>
        ))}
      </div>
      {data && data.items.length > 0 && (
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <FilterInput
            label="Search document, owner or quote"
            value={search}
            onChange={setSearch}
            placeholder="e.g. prospectus"
          />
          <FilterSelect
            label="Term type"
            value={type}
            onChange={setType}
            options={[{ value: "", label: "All types" }, ...types.map((t) => ({ value: t, label: humanize(t) }))]}
          />
        </div>
      )}
      {q.loading && !data ? (
        <LoadingBlock rows={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : items.length === 0 ? (
        <EmptyState
          title={search || type ? "No terms match the filters" : "Nothing to review"}
          action={
            search || type ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch("");
                  setType("");
                }}
              >
                Clear filters
              </Button>
            ) : (
              <LinkButton href="/documents">Open documents</LinkButton>
            )
          }
        >
          {search || type
            ? "Try a different search or term type."
            : filter === "fund"
            ? "No Fund Library terms are waiting. Library terms appear here only if you are a reviewer or admin in the fund's firm."
            : "New terms appear here after documents are processed."}
        </EmptyState>
      ) : (
        <>
          {data && data.total > data.items.length && (
            <p className="mb-2 text-xs text-ink-3">
              Showing the first {data.items.length} of {data.total} items.
            </p>
          )}
          <TableWrap label="Terms awaiting review">
            <table className={tableClass}>
              <thead>
                <tr>
                  <SortTh label="Owner" sortKey="owner" sort={sort} onSort={toggle} />
                  <SortTh label="Type" sortKey="type" sort={sort} onSort={toggle} />
                  <th className={thNum}>Value</th>
                  <SortTh label="Source" sortKey="document" sort={sort} onSort={toggle} />
                  <th className={th}>Quote</th>
                  <th className={th}>Checks</th>
                  <th className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {items.map((item) => {
                  const c = item.constraint;
                  const label = humanize(c.constraint_type);
                  return (
                    <tr key={c.id}>
                      <td className={td}>
                        <Badge tone={item.owner_type === "fund" ? "info" : "neutral"}>
                          {item.owner_type === "fund" ? "Fund" : "Household"}
                        </Badge>
                        <span className="mt-1 block">{item.owner_name}</span>
                      </td>
                      <td className={td}>
                        <Link href={detailHref(item)} className="font-medium text-accent-ink underline-offset-2 hover:underline">
                          {label}
                        </Link>
                        <span className="block text-xs text-ink-3">{humanize(c.asset_key)}</span>
                      </td>
                      <td className={tdNum}>
                        <ConstraintValue c={c} />
                      </td>
                      <td className={td}>
                        <span className="break-all text-xs">{c.document_name}</span>
                        <span className="block text-xs text-ink-3">PDF page {c.pdf_page}</span>
                      </td>
                      <td className={cx(td, "min-w-64 max-w-md")}>
                        <blockquote className="evidence-quote border-l-2 border-line-strong pl-2 text-sm">
                          “{excerpt(c.evidence_quote)}”
                        </blockquote>
                      </td>
                      <td className={td}>
                        <div className="flex flex-col items-start gap-1">
                          <QuoteVerifiedBadge verified={c.quote_verified} />
                          <AmbiguousBadge ambiguous={c.ambiguous} />
                          <ValidationIssuesBadge issues={c.validation_issues} />
                        </div>
                      </td>
                      <td className={td}>
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            variant="secondary"
                            aria-label={`Approve ${label} from ${item.owner_name}`}
                            loading={busy === `approve-${c.id}`}
                            disabled={busy !== null}
                            onClick={() => decide(item, "approve")}
                          >
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            aria-label={`Reject ${label} from ${item.owner_name}`}
                            loading={busy === `reject-${c.id}`}
                            disabled={busy !== null}
                            onClick={() => decide(item, "reject")}
                          >
                            Reject
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        </>
      )}
    </div>
  );
}
