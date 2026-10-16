"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { cx } from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { useApiQuery } from "@/lib/hooks";
import type { FundType } from "@/lib/types";
import { fundTypeLabel } from "./shared";

/**
 * Optional link from a household holding to a Fund Library entry.
 * `value` is the fund id ("" = not linked). Results are limited to the matching fund type.
 */
export function FundPicker({
  fundType,
  value,
  initialName,
  onChange,
  error,
}: {
  fundType: FundType;
  value: string;
  initialName?: string | null;
  onChange: (id: string) => void;
  error?: string | null;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [names, setNames] = useState<Record<string, string>>(() => (value && initialName ? { [value]: initialName } : {}));

  useEffect(() => {
    const t = setTimeout(() => setQ(draft.trim()), 250);
    return () => clearTimeout(t);
  }, [draft]);

  const results = useApiQuery(() => endpoints.searchFunds({ q, fund_type: fundType, limit: 20 }), [q, fundType]);

  useEffect(() => {
    if (!results.data) return;
    setNames((prev) => {
      const next = { ...prev };
      for (const f of results.data!.items) next[f.id] = f.name;
      return next;
    });
  }, [results.data]);

  const options = [...(results.data?.items ?? []).map((f) => ({ value: f.id, label: f.share_class ? `${f.name} (${f.share_class})` : f.name }))];
  if (value && !options.some((o) => o.value === value)) options.unshift({ value, label: names[value] ?? "Linked fund" });

  return (
    <fieldset className="space-y-2 rounded-md border border-line p-3 sm:col-span-2">
      <legend className="px-1 text-sm font-medium text-ink">Library fund (optional)</legend>
      <p className="text-xs text-ink-3">
        Link this holding to a {fundTypeLabel(fundType).toLowerCase()} in the Fund Library so simulations can use its
        reviewer-approved terms.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <label htmlFor={`${id}-q`} className="block text-sm font-medium text-ink">
            Search library
          </label>
          <input
            id={`${id}-q`}
            type="search"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Name, issuer or ticker"
            className="block w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-2 focus:outline-accent"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={`${id}-sel`} className="block text-sm font-medium text-ink">
            Library fund
          </label>
          <select
            id={`${id}-sel`}
            value={value}
            aria-invalid={error ? true : undefined}
            onChange={(e) => onChange(e.target.value)}
            className={cx(
              "block w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-2 focus:outline-accent",
              error && "border-risk",
            )}
          >
            <option value="">Not linked</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {results.data && results.data.items.length === 0 && (
        <p className="text-xs text-ink-3">
          No matching {fundTypeLabel(fundType).toLowerCase()} in the library.{" "}
          <Link href="/funds" className="underline">
            Add it in the Fund Library
          </Link>
          .
        </p>
      )}
      {error && <p className="text-xs font-medium text-risk">{error}</p>}
    </fieldset>
  );
}
