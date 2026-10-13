"use client";

import type { ReactNode } from "react";
import { checkPublicEnv } from "@/lib/env";

/** Renders a configuration-error screen instead of the app when public env vars are missing. */
export function ConfigGate({ children }: { children: ReactNode }) {
  const check = checkPublicEnv();
  if (check.ok) return <>{children}</>;
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div role="alert" className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-semibold text-slate-500">SlipSlopes</p>
        <h1 className="mt-1 text-xl font-semibold text-slate-900">Configuration required</h1>
        <p className="mt-2 text-sm text-slate-700">
          This deployment is missing required environment variables, so the app cannot connect to
          authentication or the API:
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 font-mono text-sm text-slate-800">
          {check.missing.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-slate-700">
          Set them (see <code className="font-mono">.env.example</code>) and rebuild. Values prefixed with{" "}
          <code className="font-mono">NEXT_PUBLIC_</code> are embedded at build time.
        </p>
      </div>
    </main>
  );
}
