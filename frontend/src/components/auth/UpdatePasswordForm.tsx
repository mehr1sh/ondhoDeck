"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button, Spinner, TextField } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { authErrorMessage, validateNewPassword } from "./validation";

export function UpdatePasswordForm() {
  const router = useRouter();
  const toast = useToast();
  const [ready, setReady] = useState<"checking" | "ok" | "missing">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    let active = true;
    // getSession waits for the client to finish exchanging the recovery code in the URL.
    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (active) setReady(data.session ? "ok" : "missing");
      })
      .catch(() => active && setReady("missing"));
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (!active) return;
      if (event === "PASSWORD_RECOVERY" || session) setReady("ok");
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validateNewPassword(password, confirm);
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSubmitting(true);
    try {
      const { error } = await getSupabaseBrowserClient().auth.updateUser({ password });
      if (error) {
        setFormError(authErrorMessage(error));
        return;
      }
      toast.success("Password updated");
      router.replace("/");
    } catch (err) {
      setFormError(authErrorMessage(err as Error));
    } finally {
      setSubmitting(false);
    }
  };

  if (ready === "checking") return <Spinner label="Verifying your reset link…" />;
  if (ready === "missing") {
    return (
      <div className="space-y-3" role="alert">
        <h1 className="text-lg font-semibold text-slate-900">Reset link invalid or expired</h1>
        <p className="text-sm text-slate-700">
          Open the most recent reset email from this browser, or request a new link.
        </p>
        <Link href="/reset-password" className="inline-block text-sm text-slate-700 underline hover:text-slate-900">
          Request a new link
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-labelledby="update-title">
      <h1 id="update-title" className="text-lg font-semibold text-slate-900">
        Choose a new password
      </h1>
      {formError && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {formError}
        </div>
      )}
      <TextField label="New password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} error={errors.password} hint="At least 8 characters." required />
      <TextField label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} required />
      <Button type="submit" className="w-full" loading={submitting}>
        Update password
      </Button>
    </form>
  );
}
