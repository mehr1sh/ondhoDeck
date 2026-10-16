"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, TextField } from "@/components/ui";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { authErrorMessage, validateEmail, validateNewPassword } from "./validation";

export function RegisterForm() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [checkEmail, setCheckEmail] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const v: typeof errors = { ...validateNewPassword(password, confirm) };
    const emailErr = validateEmail(email);
    if (emailErr) v.email = emailErr;
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSubmitting(true);
    try {
      const { data, error } = await getSupabaseBrowserClient().auth.signUp({
        email: email.trim(),
        password,
        options: {
          emailRedirectTo: `${window.location.origin}/login`,
          data: displayName.trim() ? { display_name: displayName.trim() } : undefined,
        },
      });
      if (error) {
        setFormError(authErrorMessage(error));
        return;
      }
      if (data.session) {
        router.replace("/");
        router.refresh();
        return;
      }
      // Email confirmation required (or the address is already registered).
      setCheckEmail(email.trim());
    } catch (err) {
      setFormError(authErrorMessage(err as Error));
    } finally {
      setSubmitting(false);
    }
  };

  if (checkEmail) {
    return (
      <div className="space-y-3" role="status">
        <h1 className="font-display text-[1.35rem] leading-snug text-ink">Check your email</h1>
        <p className="text-sm text-slate-700">
          We sent a confirmation link to <strong className="break-all">{checkEmail}</strong>. Open it to
          activate your OndhoDeck account, then sign in.
        </p>
        <p className="text-xs text-slate-600">
          Didn&apos;t receive it? Check your spam folder, or try registering again in a few minutes.
        </p>
        <Link href="/login" className="inline-block text-sm text-slate-700 underline hover:text-slate-900">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-labelledby="register-title">
      <h1 id="register-title" className="font-display text-[1.35rem] leading-snug text-ink">
        Create your OndhoDeck account
      </h1>
      {formError && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {formError}
        </div>
      )}
      <TextField label="Display name (optional)" autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={120} />
      <TextField label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} required />
      <TextField
        label="Password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={errors.password}
        hint="At least 8 characters."
        required
      />
      <TextField label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} required />
      <Button type="submit" className="w-full" loading={submitting}>
        Create account
      </Button>
      <p className="text-sm text-slate-700">
        Already have an account?{" "}
        <Link href="/login" className="underline hover:text-slate-900">
          Sign in
        </Link>
      </p>
    </form>
  );
}
