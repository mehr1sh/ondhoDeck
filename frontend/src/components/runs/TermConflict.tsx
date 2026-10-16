"use client";

import Link from "next/link";
import { ErrorState, TableWrap, tableClass, tbodyClass, td, tdNum, th, thNum } from "@/components/ui";
import { ReviewStatusBadge } from "@/components/badges";
import { ApiError } from "@/lib/api";
import { formatNumber, humanize } from "@/lib/format";
import type { TermConflict, TermConflictDetails } from "@/lib/types";

/** True for the 409 the analysis endpoints return when approved terms disagree. */
export function isTermConflict(e: unknown): e is ApiError & { details: TermConflictDetails } {
  if (!(e instanceof ApiError) || e.status !== 409 || e.code !== "term_conflict") return false;
  const d = e.details as Partial<TermConflictDetails> | null | undefined;
  return Boolean(d && Array.isArray(d.conflicts));
}

export function TermConflictTable({ conflicts, asOfDate }: { conflicts: TermConflict[]; asOfDate?: string }) {
  return (
    <TableWrap label="Conflicting approved terms">
      <table className={tableClass}>
        <thead>
          <tr>
            <th className={th}>Simulator input</th>
            <th className={th}>Clause type</th>
            <th className={thNum}>Value</th>
            <th className={th}>Document</th>
            <th className={thNum}>Page</th>
            <th className={th}>Status</th>
            <th className={th}>Term id</th>
          </tr>
        </thead>
        <tbody className={tbodyClass}>
          {conflicts.flatMap((c) =>
            c.candidates.map((x, i) => (
              <tr key={`${c.term}-${x.constraint_id}`}>
                {i === 0 ? (
                  <td className={td} rowSpan={c.candidates.length}>
                    <span className="font-medium">{humanize(c.term)}</span>
                    {asOfDate && <span className="block text-xs text-ink-3">as of {asOfDate}</span>}
                  </td>
                ) : null}
                {i === 0 ? (
                  <td className={td} rowSpan={c.candidates.length}>
                    {humanize(c.constraint_type)}
                    <span className="block text-xs text-ink-3">{humanize(c.asset_key)}</span>
                  </td>
                ) : null}
                <td className={tdNum}>
                  {formatNumber(x.value, 4)}
                  {x.unit ? ` ${x.unit}` : ""}
                </td>
                <td className={td}>
                  <span className="break-all">{x.document}</span>
                </td>
                <td className={tdNum}>{x.pdf_page}</td>
                <td className={td}>
                  <ReviewStatusBadge status={x.review_status} />
                </td>
                <td className={td}>
                  <code className="font-mono text-xs text-ink-3">{x.constraint_id.slice(0, 8)}</code>
                </td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </TableWrap>
  );
}

/** Explains a term conflict with the candidates and what to do; not a generic error. */
export function TermConflictNotice({ error }: { error: ApiError & { details: TermConflictDetails } }) {
  const { conflicts, as_of_date } = error.details;
  return (
    <div role="alert" className="space-y-3 rounded-md border border-caution/30 bg-caution-subtle p-4 text-sm text-ink">
      <div>
        <p className="font-semibold text-caution">Approved contract terms disagree — no result was calculated</p>
        <p className="mt-1 text-ink-2">
          {conflicts.length === 1 ? "One simulator input has" : `${conflicts.length} simulator inputs have`} more than one
          approved value{as_of_date ? ` in force on ${as_of_date}` : ""}. OndhoDeck never picks one automatically. To
          resolve it, reject or edit the clause that does not apply, or — if a newer fund document replaces an older one —
          mark the newer term as superseding the older one in the{" "}
          <Link href="/funds" className="underline">
            Fund Library
          </Link>
          . Then run again.
        </p>
      </div>
      <TermConflictTable conflicts={conflicts} asOfDate={as_of_date} />
      {error.requestId && (
        <p className="text-xs text-ink-3">
          Request ID: <code className="font-mono">{error.requestId}</code>
        </p>
      )}
    </div>
  );
}

/** Error display for simulation, stress, prevention and blind-spot requests. */
export function RunErrorState({ error }: { error: unknown }) {
  if (!error) return null;
  if (isTermConflict(error)) return <TermConflictNotice error={error} />;
  return <ErrorState error={error} />;
}
