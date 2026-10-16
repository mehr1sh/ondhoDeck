import Link from "next/link";
import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-page px-4 py-10">
      <Link href="/login" className="mb-6">
        <Brand />
      </Link>
      <div className="w-full max-w-sm rounded-md border border-line bg-surface p-6">{children}</div>
    </main>
  );
}
