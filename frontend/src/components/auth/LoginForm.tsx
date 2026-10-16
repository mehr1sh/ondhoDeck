"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button, Notice, TextField } from "@/components/ui";
import { safeNextPath } from "@/lib/authGuard";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { authErrorMessage, validateEmail } from "./validation";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params?.get("next"));
  const reason = params?.get("reason");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already signed in (or arriving from an email-confirmation link): continue.
  useEffect(() => {
    let active = true;
    getSupabaseBrowserClient()
      .auth.getSession()
      .then(({ data }) => {
        if (active && data.session && reason !== "expired") router.replace(next);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [router, next, reason]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const v: typeof errors = {};
    const emailErr = validateEmail(email);
    if (emailErr) v.email = emailErr;
    if (!password) v.password = "Enter your password.";
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSubmitting(true);
    try {
      const { error } = await getSupabaseBrowserClient().auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (error) {
        setFormError(authErrorMessage(error));
        return;
      }
      router.replace(next);
      router.refresh();
    } catch (err) {
      setFormError(authErrorMessage(err as Error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-labelledby="login-title">
      <h1 id="login-title" className="font-display text-[1.35rem] leading-snug text-ink">
        Sign in to OndhoDeck
      </h1>
      {reason === "expired" && (
        <Notice tone="warning">Your session expired. Please sign in again.</Notice>
      )}
      {formError && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {formError}
        </div>
      )}
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={errors.email}
        required
      />
      <TextField
        label="Password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={errors.password}
        required
      />
      <Button type="submit" className="w-full" loading={submitting}>
        Sign in
      </Button>
      <div className="flex flex-wrap justify-between gap-2 text-sm">
        <Link href="/reset-password" className="text-slate-700 underline hover:text-slate-900">
          Forgot password?
        </Link>
        <Link href="/register" className="text-slate-700 underline hover:text-slate-900">
          Create an account
        </Link>
      </div>
    </form>
  );
}
