import type { Metadata } from "next";
import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Reset password" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
