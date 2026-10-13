"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { ErrorState, LoadingBlock, SyntheticBadge, Badge, cx } from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { useApiQuery } from "@/lib/hooks";
import type { HouseholdOut } from "@/lib/types";

interface HouseholdContextValue {
  household: HouseholdOut;
  canEdit: boolean;
  isOwner: boolean;
  reload: () => Promise<unknown>;
}

const HouseholdContext = createContext<HouseholdContextValue | null>(null);

export function useHousehold(): HouseholdContextValue {
  const ctx = useContext(HouseholdContext);
  if (!ctx) throw new Error("useHousehold must be used inside a household route");
  return ctx;
}

/** Provider usable directly (e.g. in tests) without fetching. */
export function HouseholdProvider({
  household,
  reload = async () => undefined,
  children,
}: {
  household: HouseholdOut;
  reload?: () => Promise<unknown>;
  children: ReactNode;
}) {
  return (
    <HouseholdContext.Provider
      value={{ household, canEdit: household.role !== "viewer", isOwner: household.role === "owner", reload }}
    >
      {children}
    </HouseholdContext.Provider>
  );
}

const TABS = [
  { seg: "", label: "Overview" },
  { seg: "profile", label: "Profile" },
  { seg: "documents", label: "Documents" },
  { seg: "constraints", label: "Contract Explorer" },
  { seg: "scenarios", label: "Scenarios" },
  { seg: "history", label: "History" },
  { seg: "exports", label: "Exports" },
  { seg: "settings", label: "Settings" },
];

export function HouseholdFrame({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const pathname = usePathname() ?? "";
  const q = useApiQuery(() => endpoints.getHousehold(id), [id], Boolean(id));

  if (q.loading && !q.data) return <LoadingBlock label="Loading household…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;

  const h = q.data;
  const base = `/households/${h.id}`;
  const current = pathname.slice(base.length).split("/")[1] ?? "";
  const currentSeg = current === "runs" ? "history" : current;

  return (
    <HouseholdProvider household={h} reload={q.reload}>
      <div className="mb-4">
        <nav aria-label="Breadcrumb" className="text-xs text-slate-600">
          <Link href="/households" className="hover:underline">
            Households
          </Link>{" "}
          / <span className="text-slate-800">{h.name}</span>
        </nav>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold text-slate-900">{h.name}</h1>
          {h.is_demo && <SyntheticBadge />}
          <Badge>{h.reporting_currency}</Badge>
          <Badge tone={h.role === "viewer" ? "neutral" : "info"}>Role: {h.role}</Badge>
        </div>
        {h.is_demo && (
          <p className="mt-1 text-xs text-amber-900">
            This is a demo household. Its balances and sample contracts are synthetic and do not describe any real person
            or agreement.
          </p>
        )}
      </div>
      <nav aria-label="Household sections" className="-mx-4 mb-5 overflow-x-auto border-b border-slate-200 px-4 sm:mx-0 sm:px-0">
        <ul className="flex min-w-max gap-1">
          {TABS.map((t) => {
            const active = currentSeg === t.seg;
            return (
              <li key={t.seg}>
                <Link
                  href={t.seg ? `${base}/${t.seg}` : base}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "block border-b-2 px-3 py-2 text-sm font-medium",
                    active ? "border-lime-500 text-slate-900" : "border-transparent text-slate-600 hover:text-slate-900",
                  )}
                >
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {children}
    </HouseholdProvider>
  );
}
