"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { User } from "@supabase/supabase-js";
import { Brand } from "@/components/Brand";
import { AssistantPanel, householdIdFromPath } from "@/components/assistant/AssistantPanel";
import { Button, Spinner, cx } from "@/components/ui";
import { endpoints } from "@/lib/endpoints";
import { decideAuthRedirect } from "@/lib/authGuard";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

interface SessionContextValue {
  user: User;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside AppShell");
  return ctx;
}

const ASSISTANT_OPEN_KEY = "ondhodeck.assistant.open";

export interface NavItem {
  href: string;
  label: string;
  match: (p: string) => boolean;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Overview", match: (p) => p === "/" },
  { href: "/households", label: "Households", match: (p) => p.startsWith("/households") },
  { href: "/funds", label: "Fund Library", match: (p) => p.startsWith("/funds") },
  { href: "/documents", label: "Documents", match: (p) => p.startsWith("/documents") },
  { href: "/review", label: "Review Queue", match: (p) => p.startsWith("/review") },
  { href: "/scenarios", label: "Liquidity Scenarios", match: (p) => p.startsWith("/scenarios") },
  { href: "/reports", label: "Reports", match: (p) => p.startsWith("/reports") },
  { href: "/settings", label: "Settings", match: (p) => p.startsWith("/settings") },
];

interface ReviewCountValue {
  count: number | null;
  refresh: () => void;
}

const ReviewCountContext = createContext<ReviewCountValue>({ count: null, refresh: () => undefined });

/** Lets pages refresh the sidebar's Review Queue badge after approving or rejecting terms. */
export function useReviewCount(): ReviewCountValue {
  return useContext(ReviewCountContext);
}

/** Primary navigation. Exported separately so it can be rendered and tested without the auth guard. */
export function SidebarNav({ pathname, reviewCount }: { pathname: string; reviewCount: number | null }) {
  return (
    <nav aria-label="Main">
      <ul className="space-y-0.5">
        {NAV.map((item) => {
          const active = item.match(pathname);
          const showCount = item.href === "/review" && reviewCount !== null && reviewCount > 0;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex items-center justify-between border-l-2 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
                  active
                    ? "border-accent bg-accent-subtle font-semibold text-accent-ink"
                    : "border-transparent font-medium text-ink-2 hover:bg-surface-muted hover:text-ink",
                )}
              >
                <span>{item.label}</span>
                {showCount && (
                  <span
                    className="ml-2 rounded-sm bg-ink px-1.5 py-0.5 text-[11px] font-semibold leading-none text-white tabular-nums"
                    aria-label={`${reviewCount} items awaiting review`}
                  >
                    {reviewCount}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Client-side guard + application chrome (sidebar on desktop, drawer on mobile). */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    let active = true;
    const redirectIfNeeded = (u: User | null) => {
      const search = typeof window !== "undefined" ? window.location.search : "";
      const target = decideAuthRedirect(pathname, search, Boolean(u));
      if (target) router.replace(target);
    };
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      const u = data.session?.user ?? null;
      setUser(u);
      setChecking(false);
      redirectIfNeeded(u);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      const u = session?.user ?? null;
      setUser(u);
      if (!u) redirectIfNeeded(null);
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
    // Only re-check on mount; auth changes arrive through onAuthStateChange.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => setDrawerOpen(false), [pathname]);

  // Assistant: a floating box in the bottom-right corner, minimised to a button. Open by default on large
  // screens and minimised on small ones until the advisor chooses; the choice is remembered in this browser.
  const [assistantOpen, setAssistantOpen] = useState(false);
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(ASSISTANT_OPEN_KEY);
    } catch {
      // storage unavailable: use the default
    }
    setAssistantOpen(stored !== null ? stored === "true" : !!window.matchMedia?.("(min-width: 1024px)").matches);
  }, []);
  const showAssistant = (open: boolean) => {
    setAssistantOpen(open);
    try {
      window.localStorage.setItem(ASSISTANT_OPEN_KEY, String(open));
    } catch {
      // storage unavailable: the choice lasts for this page view
    }
  };

  const [reviewCount, setReviewCount] = useState<number | null>(null);
  const refreshReviewCount = useCallback(() => {
    endpoints
      .reviewQueue(1)
      .then((r) => setReviewCount(r.total))
      .catch(() => setReviewCount(null));
  }, []);
  useEffect(() => {
    if (user) refreshReviewCount();
  }, [user, pathname, refreshReviewCount]);

  const signOut = async () => {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
  };

  if (checking || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page">
        <Spinner label="Checking your session…" />
      </div>
    );
  }

  const nav = <SidebarNav pathname={pathname} reviewCount={reviewCount} />;

  return (
    <SessionContext.Provider value={{ user, signOut }}>
      <ReviewCountContext.Provider value={{ count: reviewCount, refresh: refreshReviewCount }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="min-h-screen bg-page lg:flex">
        {/* Desktop sidebar */}
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface py-5 pr-3 lg:flex">
          <Link href="/" className="mb-7 block pl-4">
            <Brand />
          </Link>
          {nav}
          <div className="mt-auto space-y-2 border-t border-line pl-4 pt-4">
            <p className="truncate text-xs text-ink-3" title={user.email ?? undefined}>
              {user.email}
            </p>
            <Button variant="secondary" size="sm" onClick={signOut} className="w-full">
              Sign out
            </Button>
          </div>
        </aside>

        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-2 lg:hidden">
          <Link href="/">
            <Brand compact />
          </Link>
          <span className="font-display text-base text-ink">OndhoDeck</span>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={drawerOpen}
            aria-controls="mobile-drawer"
            onClick={() => setDrawerOpen((v) => !v)}
          >
            {drawerOpen ? "Close" : "Menu"}
          </Button>
        </header>
        {drawerOpen && (
          <div id="mobile-drawer" className="sticky top-[49px] z-20 max-h-[calc(100vh-49px)] overflow-y-auto border-b border-line bg-surface py-3 pr-3 lg:hidden">
            {nav}
            <div className="mt-4 flex items-center justify-between gap-2 border-t border-line pl-4 pt-3">
              <span className="truncate text-xs text-ink-3">{user.email}</span>
              <Button variant="secondary" size="sm" onClick={signOut}>
                Sign out
              </Button>
            </div>
          </div>
        )}

        <main id="main" className="min-w-0 flex-1 px-4 pb-24 pt-6 sm:px-6 lg:px-12 lg:pt-10">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>

      {/* One assistant instance stays mounted on every page (minimising only hides it), so a conversation and
          a reply being streamed survive navigation. */}
      <div
        id="assistant-panel"
        className={cx(
          "fixed bottom-4 right-4 z-40 h-[min(640px,calc(100vh-6rem))] w-[calc(100vw-2rem)] max-w-[400px]",
          "flex-col overflow-hidden rounded-lg border border-line-strong bg-surface shadow-2xl",
          assistantOpen ? "flex" : "hidden",
        )}
      >
        <AssistantPanel householdId={householdIdFromPath(pathname)} onHide={() => showAssistant(false)} />
      </div>
      {!assistantOpen && (
        <Button
          variant="accent"
          onClick={() => showAssistant(true)}
          aria-controls="assistant-panel"
          aria-expanded={false}
          className="fixed bottom-4 right-4 z-40 px-5 shadow-lg"
        >
          Assistant
        </Button>
      )}
      </ReviewCountContext.Provider>
    </SessionContext.Provider>
  );
}
