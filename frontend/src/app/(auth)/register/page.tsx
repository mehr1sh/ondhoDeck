import type { Metadata } from "next";
import { Suspense } from "react";
import { RegisterForm } from "@/components/auth/RegisterForm";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Create account" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <RegisterForm />
    </Suspense>
  );
}
