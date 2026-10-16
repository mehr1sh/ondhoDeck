"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { Breadcrumbs, ErrorState, LoadingBlock, SyntheticBadge, Badge, cx } from "@/components/ui";
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

export const HOUSEHOLD_TABS = [
  { seg: "", label: "Overview" },
  { seg: "profile", label: "Profile" },
  { seg: "documents", label: "Documents" },
  { seg: "constraints", label: "Terms" },
  { seg: "scenarios", label: "Scenarios" },
  { seg: "exports", label: "Reports" },
  { seg: "history", label: "History" },
  { seg: "settings", label: "Settings" },
];

/** Sub-page labels for the breadcrumb trail below a tab (e.g. a run under Scenarios). */
function subPageLabel(parts: string[]): string | null {
  const [seg, id, child] = parts;
  if (!id) return null;
  if (seg === "runs") return "Analysis result";
  if (seg === "documents") return "Document";
  if (seg === "constraints") return "Term";
  if (seg === "scenarios") {
    if (id === "new") return "New scenario";
    if (child === "stress") return "Reverse stress test";
    if (child === "prevention") return "Prevention planner";
    return "Scenario";
  }
  return null;
}

export function HouseholdFrame({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const pathname = usePathname() ?? "";
  const q = useApiQuery(() => endpoints.getHousehold(id), [id], Boolean(id));

  if (q.loading && !q.data) return <LoadingBlock label="Loading household…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;

  const h = q.data;
  const base = `/households/${h.id}`;
  const parts = pathname.slice(base.length).split("/").filter(Boolean);
  const current = parts[0] ?? "";
  const currentSeg = current === "runs" ? "scenarios" : current;
  const tab = HOUSEHOLD_TABS.find((t) => t.seg === currentSeg) ?? HOUSEHOLD_TABS[0]!;
  const sub = subPageLabel(parts);
  const crumbs: Array<{ label: string; href?: string }> = [
    { label: "Households", href: "/households" },
    { label: h.name, href: base },
    { label: tab.label, href: tab.seg ? `${base}/${tab.seg}` : base },
  ];
  if (sub) crumbs.push({ label: sub });

  return (
    <HouseholdProvider household={h} reload={q.reload}>
      <div className="mb-4">
        <Breadcrumbs items={crumbs} />
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <h1 className="font-display text-[1.75rem] leading-tight text-ink">{h.name}</h1>
          {h.is_demo && <SyntheticBadge />}
          <Badge>{h.reporting_currency}</Badge>
          <Badge tone={h.role === "viewer" ? "neutral" : "info"}>Role: {h.role}</Badge>
        </div>
        {h.is_demo && (
          <p className="mt-1 text-xs text-caution">
            This is a demo household. Its balances and sample contracts are synthetic and do not describe any real person
            or agreement.
          </p>
        )}
      </div>
      <nav aria-label="Household sections" className="-mx-4 mb-6 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
        <ul className="flex min-w-max gap-1">
          {HOUSEHOLD_TABS.map((t) => {
            const active = currentSeg === t.seg;
            return (
              <li key={t.seg}>
                <Link
                  href={t.seg ? `${base}/${t.seg}` : base}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "-mb-px block border-b-2 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
                    active ? "border-accent font-semibold text-ink" : "border-transparent font-medium text-ink-3 hover:text-ink",
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
