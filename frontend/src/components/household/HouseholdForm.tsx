"use client";

import { useState, type FormEvent } from "react";
import { Button, ErrorState, SelectField, TextAreaField, TextField } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { MONTH_NAMES } from "@/lib/format";
import type { HouseholdIn, HouseholdOut } from "@/lib/types";

export const CURRENCY_RE = /^[A-Za-z]{3}$/;

export function HouseholdForm({
  initial,
  submitLabel,
  onSubmit,
  disabled,
}: {
  initial?: Partial<HouseholdOut>;
  submitLabel: string;
  onSubmit: (body: HouseholdIn) => Promise<void>;
  disabled?: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [currency, setCurrency] = useState(initial?.reporting_currency ?? "USD");
  const [startMonth, setStartMonth] = useState(String(initial?.start_calendar_month ?? 1));
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (!name.trim()) v.name = "Enter a household name.";
    else if (name.trim().length > 160) v.name = "Use at most 160 characters.";
    if (!CURRENCY_RE.test(currency.trim())) v.reporting_currency = "Use a 3-letter ISO 4217 code, e.g. USD.";
    if (notes.length > 4000) v.notes = "Use at most 4000 characters.";
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSubmitting(true);
    try {
      await onSubmit({
        name: name.trim(),
        reporting_currency: currency.trim().toUpperCase(),
        start_calendar_month: Number(startMonth),
        notes: notes.trim() ? notes.trim() : null,
      });
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setFormError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="max-w-xl space-y-4">
      {formError ? <ErrorState error={formError} /> : null}
      <TextField label="Household name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} required disabled={disabled} maxLength={160} />
      <TextField
        label="Reporting currency"
        value={currency}
        onChange={(e) => setCurrency(e.target.value.toUpperCase())}
        error={errors.reporting_currency}
        hint="ISO 4217 code. All results are reported in this currency."
        required
        maxLength={3}
        disabled={disabled}
      />
      <SelectField
        label="Projection start month"
        value={startMonth}
        onChange={(e) => setStartMonth(e.target.value)}
        error={errors.start_calendar_month}
        hint="Calendar month of projection month 1."
        options={MONTH_NAMES.map((m, i) => ({ value: String(i + 1), label: m }))}
        disabled={disabled}
      />
      <TextAreaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} error={errors.notes} maxLength={4000} disabled={disabled} />
      <Button type="submit" loading={submitting} disabled={disabled}>
        {submitLabel}
      </Button>
    </form>
  );
}
