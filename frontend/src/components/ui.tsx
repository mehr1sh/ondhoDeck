"use client";

import Link from "next/link";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { describeError } from "@/lib/hooks";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// ----------------------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "danger" | "ghost" | "accent";
const variantClass: Record<Variant, string> = {
  primary: "bg-slate-800 text-white hover:bg-slate-700 border-slate-800",
  accent: "bg-lime-400 text-slate-900 hover:bg-lime-300 border-lime-500",
  secondary: "bg-white text-slate-800 hover:bg-slate-50 border-slate-300",
  danger: "bg-red-700 text-white hover:bg-red-600 border-red-700",
  ghost: "bg-transparent text-slate-700 hover:bg-slate-100 border-transparent",
};

const buttonBase =
  "inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700 disabled:cursor-not-allowed disabled:opacity-50";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, disabled, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(buttonBase, variantClass[variant], size === "sm" && "px-2 py-1 text-xs", className)}
      {...rest}
    >
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  );
});

export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: "sm" | "md";
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={cx(buttonBase, variantClass[variant], size === "sm" && "px-2 py-1 text-xs", className)}>
      {children}
    </Link>
  );
}

// ----------------------------------------------------------------------------- feedback

export function Spinner({ size = "md", label }: { size?: "sm" | "md"; label?: string }) {
  return (
    <span role={label ? "status" : undefined} className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className={cx(
          "inline-block animate-spin rounded-full border-2 border-slate-300 border-t-slate-700",
          size === "sm" ? "h-3.5 w-3.5" : "h-5 w-5",
        )}
      />
      {label && <span className="text-sm text-slate-600">{label}</span>}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("animate-pulse rounded bg-slate-200", className)} />;
}

export function LoadingBlock({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 py-4">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={cx("h-5", i % 2 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <h3 className="text-base font-semibold text-slate-800">{title}</h3>
      {children && <div className="mx-auto mt-2 max-w-prose text-sm text-slate-600">{children}</div>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const d = describeError(error);
  if (d.status === 404) {
    return (
      <div role="alert" className="rounded-lg border border-slate-200 bg-white px-6 py-10 text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">404</p>
        <h2 className="mt-1 text-lg font-semibold text-slate-900">Not found</h2>
        <p className="mt-2 text-sm text-slate-600">
          This item does not exist or you do not have access to it.
        </p>
        <div className="mt-4">
          <LinkButton href="/">Back to dashboard</LinkButton>
        </div>
      </div>
    );
  }
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
      <p className="font-semibold">{d.title}</p>
      <p className="mt-1">{d.message}</p>
      {d.requestId && (
        <p className="mt-1 text-xs text-red-800">
          Request ID: <code className="font-mono">{d.requestId}</code>
        </p>
      )}
      {onRetry && d.status !== 401 && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning" | "success" | "danger";
  title?: string;
  children: ReactNode;
}) {
  const tones = {
    info: "border-slate-300 bg-slate-50 text-slate-800",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    danger: "border-red-300 bg-red-50 text-red-900",
  } as const;
  return (
    <div className={cx("rounded-md border px-3 py-2 text-sm", tones[tone])}>
      {title && <p className="font-semibold">{title}</p>}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}

// ----------------------------------------------------------------------------- badges

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger" | "accent";
const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-300",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-50 text-amber-900 ring-amber-200",
  danger: "bg-red-50 text-red-800 ring-red-200",
  accent: "bg-lime-200 text-slate-900 ring-lime-400",
};

export function Badge({ tone = "neutral", children, title }: { tone?: BadgeTone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        badgeTones[tone],
      )}
    >
      {children}
    </span>
  );
}

// ----------------------------------------------------------------------------- layout

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {description && <div className="mt-1 text-sm text-slate-600">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "danger" | "success" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p
        className={cx(
          "mt-1 text-lg font-semibold tabular-nums",
          tone === "danger" ? "text-red-700" : tone === "success" ? "text-emerald-700" : "text-slate-900",
        )}
      >
        {value}
      </p>
      {hint && <div className="mt-1 text-xs text-slate-600">{hint}</div>}
    </div>
  );
}

/** Horizontally scrollable table container. */
export function TableWrap({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export const th = "whitespace-nowrap bg-slate-50 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-600";
export const thNum = cx(th, "text-right");
export const td = "px-3 py-2 align-top text-sm text-slate-800";
export const tdNum = "px-3 py-2 align-top text-right text-sm tabular-nums whitespace-nowrap text-slate-800";
export const tableClass = "min-w-full divide-y divide-slate-200";
export const tbodyClass = "divide-y divide-slate-100";

// ----------------------------------------------------------------------------- forms

interface FieldShellProps {
  id: string;
  label: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  required?: boolean;
  children: ReactNode;
  badge?: ReactNode;
}

function FieldShell({ id, label, error, hint, required, children, badge }: FieldShellProps) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-800">
        <span>
          {label}
          {required && (
            <span aria-hidden="true" className="text-red-700">
              {" "}
              *
            </span>
          )}
        </span>
        {badge}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-slate-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

const inputClass =
  "block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-slate-600 focus:outline-2 focus:outline-slate-600 disabled:bg-slate-100 aria-[invalid=true]:border-red-600";

function describedBy(id: string, error?: string | null, hint?: ReactNode) {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  badge?: ReactNode;
  id?: string;
}

export function TextField({ label, error, hint, badge, id, required, className, ...rest }: TextFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} error={error} hint={hint} required={required} badge={badge}>
      <input
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        aria-required={required || undefined}
        className={cx(inputClass, "tabular-nums", className)}
        {...rest}
      />
    </FieldShell>
  );
}

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> {
  label: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  options: Array<{ value: string; label: string }>;
  id?: string;
}

export function SelectField({ label, error, hint, options, id, required, className, ...rest }: SelectFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} error={error} hint={hint} required={required}>
      <select
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        className={cx(inputClass, className)}
        {...rest}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

export interface TextAreaFieldProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  label: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  id?: string;
}

export function TextAreaField({ label, error, hint, id, required, className, ...rest }: TextAreaFieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} error={error} hint={hint} required={required}>
      <textarea
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        className={cx(inputClass, "min-h-20", className)}
        {...rest}
      />
    </FieldShell>
  );
}

export function CheckboxField({
  label,
  checked,
  onChange,
  disabled,
  hint,
  id,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  hint?: ReactNode;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <input
          id={fid}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          aria-describedby={hint ? `${fid}-hint` : undefined}
          className="h-4 w-4 rounded border-slate-400 text-slate-800 focus:outline-2 focus:outline-slate-600"
        />
        <label htmlFor={fid} className="text-sm font-medium text-slate-800">
          {label}
        </label>
      </div>
      {hint && (
        <p id={`${fid}-hint`} className="text-xs text-slate-600">
          {hint}
        </p>
      )}
    </div>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return <ErrorState error={error} />;
}

// ----------------------------------------------------------------------------- dialog

export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>(
      "input, select, textarea, button:not([data-dialog-close]), [href]",
    );
    (first ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && el) {
        const items = Array.from(
          el.querySelectorAll<HTMLElement>("input, select, textarea, button, [href]"),
        ).filter((n) => !n.hasAttribute("disabled"));
        if (!items.length) return;
        const firstItem = items[0]!;
        const lastItem = items[items.length - 1]!;
        if (e.shiftKey && document.activeElement === firstItem) {
          e.preventDefault();
          lastItem.focus();
        } else if (!e.shiftKey && document.activeElement === lastItem) {
          e.preventDefault();
          firstItem.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-0 sm:items-center sm:p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-xl sm:max-w-lg sm:rounded-lg"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id={titleId} className="text-base font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            data-dialog-close
            onClick={onClose}
            className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>
        <div className="space-y-3 px-4 py-4 text-sm text-slate-700">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- pagination

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center justify-between gap-2 text-sm text-slate-700">
      <span className="tabular-nums">
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </nav>
  );
}

export function SyntheticBadge() {
  return (
    <Badge tone="warning" title="Synthetic demo data, not a real household or contract">
      Synthetic demo data
    </Badge>
  );
}
