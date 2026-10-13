import Link from "next/link";
import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-100 px-4 py-10">
      <Link href="/login" className="mb-6">
        <Brand />
      </Link>
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">{children}</div>
    </main>
  );
}
