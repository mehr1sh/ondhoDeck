"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Button, CheckboxField, ErrorState, SelectField, TextAreaField, TextField } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { humanize, normalizeDecimalInput, parseDecimal } from "@/lib/format";

export type FieldType =
  | "text"
  | "textarea"
  | "money"
  | "select"
  | "int"
  | "checkbox"
  | "date"
  | "currency"
  | "percent"
  | "custom";

export interface CustomFieldProps {
  value: string;
  set: (v: string) => void;
  error?: string;
  values: FormValues;
  initial?: Record<string, unknown> | null;
}

export type FormValues = Record<string, string | boolean>;

export interface FieldDef {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: readonly string[];
  min?: number;
  max?: number;
  maxLength?: number;
  hint?: string;
  showIf?: (values: FormValues) => boolean;
  /** Clear this field when any of these fields change (e.g. a fund link when the asset kind changes). */
  resetOn?: string[];
  /** Renderer for `custom` fields; the value is a string ("" = null in the API body). */
  render?: (props: CustomFieldProps) => ReactNode;
}

const MONEY_RE = /^\d{1,16}(\.\d{1,2})?$/;
const CURRENCY_RE = /^[A-Za-z]{3}$/;

/** Converts an API record into string form values. Percent fields are shown as percentages. */
export function toFormValues(fields: FieldDef[], record?: Record<string, unknown> | null): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    const raw = record?.[f.name];
    if (f.type === "checkbox") out[f.name] = Boolean(raw);
    else if (raw === null || raw === undefined) {
      out[f.name] = f.type === "currency" ? "USD" : f.type === "select" ? (f.options?.[0] ?? "") : "";
    } else if (f.type === "percent") {
      const n = parseDecimal(raw);
      out[f.name] = n === null ? "" : String(Number((n * 100).toPrecision(12)));
    } else out[f.name] = String(raw);
  }
  return out;
}

export function validateValues(fields: FieldDef[], values: FormValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    if (f.showIf && !f.showIf(values)) continue;
    const v = values[f.name];
    if (f.type === "checkbox") continue;
    const s = typeof v === "string" ? v.trim() : "";
    if (!s) {
      if (f.required) errors[f.name] = `${f.label} is required.`;
      continue;
    }
    if (f.maxLength && s.length > f.maxLength) errors[f.name] = `Use at most ${f.maxLength} characters.`;
    if (f.type === "money") {
      const norm = normalizeDecimalInput(s);
      if (norm.startsWith("-")) errors[f.name] = "Amount cannot be negative.";
      else if (!MONEY_RE.test(norm)) errors[f.name] = "Enter an amount with up to 2 decimal places.";
    }
    if (f.type === "int") {
      if (!/^\d+$/.test(s)) errors[f.name] = "Enter a whole number.";
      else {
        const n = Number(s);
        if (f.min !== undefined && n < f.min) errors[f.name] = `Must be at least ${f.min}.`;
        if (f.max !== undefined && n > f.max) errors[f.name] = `Must be at most ${f.max}.`;
      }
    }
    if (f.type === "percent") {
      const n = parseDecimal(s);
      if (n === null) errors[f.name] = "Enter a number.";
      else if (f.min !== undefined && n < f.min) errors[f.name] = `Must be at least ${f.min}%.`;
      else if (f.max !== undefined && n > f.max) errors[f.name] = `Must be at most ${f.max}%.`;
    }
    if (f.type === "currency" && !CURRENCY_RE.test(s)) errors[f.name] = "Use a 3-letter ISO 4217 code.";
    if (f.type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(s)) errors[f.name] = "Use the format YYYY-MM-DD.";
  }
  return errors;
}

/** Converts form values into an API body. Hidden fields are sent as null. */
export function toBody(fields: FieldDef[], values: FormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.showIf && !f.showIf(values)) {
      body[f.name] = null;
      continue;
    }
    if (f.type === "checkbox") {
      body[f.name] = Boolean(v);
      continue;
    }
    const s = typeof v === "string" ? v.trim() : "";
    if (!s) {
      body[f.name] = null;
      continue;
    }
    switch (f.type) {
      case "money":
        body[f.name] = normalizeDecimalInput(s);
        break;
      case "int":
        body[f.name] = Number(s);
        break;
      case "percent": {
        const n = parseDecimal(s) ?? 0;
        body[f.name] = String(Number((n / 100).toPrecision(12)));
        break;
      }
      case "currency":
        body[f.name] = s.toUpperCase();
        break;
      default:
        body[f.name] = s;
    }
  }
  return body;
}

export function RecordForm({
  fields,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  fields: FieldDef[];
  initial?: Record<string, unknown> | null;
  submitLabel: string;
  onSubmit: (body: Record<string, unknown>) => Promise<void>;
  onCancel?: () => void;
}) {
  const [values, setValues] = useState<FormValues>(() => toFormValues(fields, initial));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (name: string, v: string | boolean) =>
    setValues((prev) => {
      const next: FormValues = { ...prev, [name]: v };
      for (const f of fields) if (f.resetOn?.includes(name) && prev[name] !== v) next[f.name] = "";
      return next;
    });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validateValues(fields, values);
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSubmitting(true);
    try {
      await onSubmit(toBody(fields, values));
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setFormError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      {formError ? <ErrorState error={formError} /> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => {
          if (f.showIf && !f.showIf(values)) return null;
          const common = { label: f.label, error: errors[f.name], hint: f.hint, required: f.required };
          const val = values[f.name];
          if (f.type === "custom" && f.render) {
            return (
              <div key={f.name} className="sm:col-span-2">
                {f.render({ value: String(val ?? ""), set: (v) => set(f.name, v), error: errors[f.name], values, initial })}
              </div>
            );
          }
          if (f.type === "checkbox") {
            return (
              <div key={f.name} className="sm:col-span-2">
                <CheckboxField label={f.label} checked={Boolean(val)} onChange={(c) => set(f.name, c)} hint={f.hint} />
              </div>
            );
          }
          if (f.type === "select") {
            return (
              <SelectField
                key={f.name}
                {...common}
                value={String(val)}
                onChange={(e) => set(f.name, e.target.value)}
                options={(f.options ?? []).map((o) => ({ value: o, label: humanize(o) }))}
              />
            );
          }
          if (f.type === "textarea") {
            return (
              <div key={f.name} className="sm:col-span-2">
                <TextAreaField {...common} value={String(val)} onChange={(e) => set(f.name, e.target.value)} maxLength={f.maxLength} />
              </div>
            );
          }
          return (
            <TextField
              key={f.name}
              {...common}
              type={f.type === "date" ? "date" : "text"}
              inputMode={f.type === "money" || f.type === "percent" ? "decimal" : f.type === "int" ? "numeric" : undefined}
              value={String(val)}
              maxLength={f.type === "currency" ? 3 : f.maxLength}
              onChange={(e) => set(f.name, f.type === "currency" ? e.target.value.toUpperCase() : e.target.value)}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2 pt-1">
        <Button type="submit" loading={submitting}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
