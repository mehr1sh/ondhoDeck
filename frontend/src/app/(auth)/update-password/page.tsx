import type { Metadata } from "next";
import { Suspense } from "react";
import { UpdatePasswordForm } from "@/components/auth/UpdatePasswordForm";
import { Spinner } from "@/components/ui";

export const metadata: Metadata = { title: "Update password" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <UpdatePasswordForm />
    </Suspense>
  );
}
