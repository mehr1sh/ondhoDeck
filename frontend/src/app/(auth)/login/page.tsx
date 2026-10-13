import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Sign in" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <LoginForm />
    </Suspense>
  );
}
