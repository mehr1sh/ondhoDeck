"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { User } from "@supabase/supabase-js";
import { Brand } from "@/components/Brand";
import { Button, Spinner, cx } from "@/components/ui";
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

const NAV = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/households", label: "Households", match: (p: string) => p.startsWith("/households") },
  { href: "/settings", label: "Settings", match: (p: string) => p.startsWith("/settings") },
];

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

  const signOut = async () => {
    await getSupabaseBrowserClient().auth.signOut();
    router.replace("/login");
  };

  if (checking || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100">
        <Spinner label="Checking your session…" />
      </div>
    );
  }

  const nav = (
    <nav aria-label="Main" className="space-y-1">
      {NAV.map((item) => {
        const active = item.match(pathname);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "block rounded-md px-3 py-2 text-sm font-medium",
              active ? "bg-slate-800 text-white" : "text-slate-700 hover:bg-slate-200",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <SessionContext.Provider value={{ user, signOut }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="min-h-screen bg-slate-100 lg:flex">
        {/* Desktop sidebar */}
        <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-slate-50 p-4 lg:flex">
          <Link href="/" className="mb-6 block">
            <Brand />
          </Link>
          {nav}
          <div className="mt-auto space-y-2 border-t border-slate-200 pt-4">
            <p className="truncate text-xs text-slate-600" title={user.email ?? undefined}>
              {user.email}
            </p>
            <Button variant="secondary" size="sm" onClick={signOut} className="w-full">
              Sign out
            </Button>
          </div>
        </aside>

        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
          <Link href="/">
            <Brand compact />
          </Link>
          <span className="text-sm font-semibold text-slate-900">SlipSlopes</span>
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
          <div id="mobile-drawer" className="border-b border-slate-200 bg-slate-50 p-4 lg:hidden">
            {nav}
            <div className="mt-4 flex items-center justify-between gap-2 border-t border-slate-200 pt-3">
              <span className="truncate text-xs text-slate-600">{user.email}</span>
              <Button variant="secondary" size="sm" onClick={signOut}>
                Sign out
              </Button>
            </div>
          </div>
        )}

        <main id="main" className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </SessionContext.Provider>
  );
}
