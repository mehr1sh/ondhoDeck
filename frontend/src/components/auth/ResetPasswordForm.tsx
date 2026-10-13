"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button, TextField } from "@/components/ui";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { authErrorMessage, validateEmail } from "./validation";

export function ResetPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validateEmail(email);
    setError(v);
    setFormError(null);
    if (v) return;
    setSubmitting(true);
    try {
      const { error: err } = await getSupabaseBrowserClient().auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/update-password`,
      });
      if (err) {
        setFormError(authErrorMessage(err));
        return;
      }
      setSent(true);
    } catch (err) {
      setFormError(authErrorMessage(err as Error));
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div className="space-y-3" role="status">
        <h1 className="text-lg font-semibold text-slate-900">Check your email</h1>
        <p className="text-sm text-slate-700">
          If an account exists for <strong className="break-all">{email.trim()}</strong>, a password reset link is on its
          way. The link opens a page where you can choose a new password.
        </p>
        <Link href="/login" className="inline-block text-sm text-slate-700 underline hover:text-slate-900">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-labelledby="reset-title">
      <h1 id="reset-title" className="text-lg font-semibold text-slate-900">
        Reset your password
      </h1>
      <p className="text-sm text-slate-600">Enter your account email and we will send you a reset link.</p>
      {formError && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {formError}
        </div>
      )}
      <TextField label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={error} required />
      <Button type="submit" className="w-full" loading={submitting}>
        Send reset link
      </Button>
      <Link href="/login" className="inline-block text-sm text-slate-700 underline hover:text-slate-900">
        Back to sign in
      </Link>
    </form>
  );
}
