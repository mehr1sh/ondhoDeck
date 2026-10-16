"use client";

import Link from "next/link";
import {
  forwardRef,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
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
  primary: "bg-accent text-white hover:bg-accent-hover border-accent",
  accent: "bg-accent text-white hover:bg-accent-hover border-accent",
  secondary: "bg-surface text-ink hover:bg-surface-muted border-ink-3/70",
  danger: "bg-risk text-white hover:bg-[#832424] border-risk",
  ghost: "bg-transparent text-ink-2 hover:bg-surface-muted border-transparent",
};

const buttonBase =
  "inline-flex items-center justify-center gap-2 rounded-sm border px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50";

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
    <div className="rounded-sm border border-line bg-surface px-6 py-10 text-center">
      <h3 className="font-display text-lg text-ink">{title}</h3>
      {children && <div className="mx-auto mt-2 max-w-prose text-sm text-slate-600">{children}</div>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const d = describeError(error);
  if (d.status === 404) {
    return (
      <div role="alert" className="rounded-sm border border-line bg-surface px-6 py-10 text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">404</p>
        <h2 className="font-display mt-1 text-xl text-ink">Not found</h2>
        <p className="mt-2 text-sm text-slate-600">
          This item does not exist or you do not have access to it.
        </p>
        <div className="mt-4">
          <LinkButton href="/">Back to overview</LinkButton>
        </div>
      </div>
    );
  }
  return (
    <div role="alert" className="rounded-md border border-risk/30 bg-risk-subtle px-4 py-3 text-sm text-risk">
      <p className="font-semibold">{d.title}</p>
      <p className="mt-1">{d.message}</p>
      {d.requestId && (
        <p className="mt-1 text-xs">
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
    info: "border-line bg-surface-muted text-ink-2",
    warning: "border-caution/30 bg-caution-subtle text-caution",
    success: "border-accent/30 bg-accent-subtle text-accent-ink",
    danger: "border-risk/30 bg-risk-subtle text-risk",
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
  neutral: "bg-surface-muted text-ink-2 ring-line-strong",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  success: "bg-accent-subtle text-accent-ink ring-accent/30",
  warning: "bg-caution-subtle text-caution ring-caution/30",
  danger: "bg-risk-subtle text-risk ring-risk/30",
  accent: "bg-accent-subtle text-accent-ink ring-accent/40",
};

/** Status label with a restrained tone; the text always carries the meaning. */
export function StatusBadge({ tone = "neutral", label, title }: { tone?: BadgeTone; label: string; title?: string }) {
  return (
    <Badge tone={tone} title={title}>
      {label}
    </Badge>
  );
}

export function Badge({ tone = "neutral", children, title }: { tone?: BadgeTone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded-sm px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
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
    <section className={cx("rounded-md border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          {title && <h2 className="font-display text-base text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  level = 1,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Small context line above the title (e.g. breadcrumbs). */
  eyebrow?: ReactNode;
  /** Heading level; nested pages inside a household frame use 2. */
  level?: 1 | 2;
}) {
  const H = level === 1 ? "h1" : "h2";
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line pb-5">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-xs text-ink-3">{eyebrow}</div>}
        <H className={cx("font-display text-ink", level === 1 ? "text-[1.75rem] leading-tight" : "text-[1.35rem] leading-snug")}>
          {title}
        </H>
        {description && <div className="mt-1.5 max-w-3xl text-sm text-ink-3">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** A titled content section separated by a hairline rule (no card chrome). */
export function Section({
  title,
  description,
  action,
  children,
  id,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  const auto = useId();
  const headingId = id ?? auto;
  return (
    <section aria-labelledby={headingId} className={cx("space-y-3", className)}>
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-2">
        <div className="min-w-0">
          <h2 id={headingId} className="font-display text-lg text-ink">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-ink-3">{description}</p>}
        </div>
        {action && <div className="flex flex-wrap items-center gap-2 text-sm">{action}</div>}
      </div>
      {children}
    </section>
  );
}

/** Breadcrumb trail. The last item is the current page. */
export function Breadcrumbs({ items }: { items: Array<{ label: ReactNode; href?: string }> }) {
  return (
    <nav aria-label="Breadcrumb" className="text-xs text-ink-3">
      <ol className="flex flex-wrap items-center gap-1">
        {items.map((it, i) => {
          const last = i === items.length - 1;
          return (
            <li key={i} className="flex items-center gap-1">
              {it.href && !last ? (
                <Link href={it.href} className="underline-offset-2 hover:text-ink hover:underline">
                  {it.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "text-ink-2" : undefined}>
                  {it.label}
                </span>
              )}
              {!last && <span aria-hidden="true">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Small-print footnote, e.g. "Modelled projection — not a guaranteed outcome." */
export function Disclosure({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("small-print border-t border-line pt-2", className)}>{children}</div>;
}

// ----------------------------------------------------------------------------- workflow

export type StepState = "done" | "current" | "attention" | "todo" | "blocked";

export interface WorkflowStep {
  key: string;
  label: string;
  state: StepState;
  /** Short status text derived from real data, e.g. "3 documents, 1 failed". */
  detail?: string;
  href?: string;
}

const STEP_STATE_LABEL: Record<StepState, string> = {
  done: "Complete",
  current: "Next",
  attention: "Needs attention",
  todo: "Not started",
  blocked: "Waiting on an earlier step",
};

/** Horizontal (wrapping) progress strip. Each step shows its state as text, never by colour alone. */
export function WorkflowProgress({ steps, label = "Workflow progress" }: { steps: WorkflowStep[]; label?: string }) {
  return (
    <nav aria-label={label}>
      <ol className="grid overflow-hidden rounded-sm border-l border-t border-line bg-surface sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {steps.map((s, i) => {
          const body = (
            <>
              <span className="flex items-center gap-2 text-xs text-ink-3">
                <span
                  aria-hidden="true"
                  className={cx(
                    "inline-flex h-5 w-5 items-center justify-center rounded-full border text-[11px] tabular-nums",
                    s.state === "done" && "border-accent bg-accent text-white",
                    s.state === "current" && "border-ink bg-ink text-white",
                    s.state === "attention" && "border-caution text-caution",
                    (s.state === "todo" || s.state === "blocked") && "border-line-strong text-ink-3",
                  )}
                >
                  {s.state === "done" ? "✓" : i + 1}
                </span>
                <span
                  className={cx(
                    s.state === "attention" && "text-caution",
                    s.state === "done" && "text-accent-ink",
                    s.state === "current" && "font-medium text-ink",
                  )}
                >
                  {STEP_STATE_LABEL[s.state]}
                </span>
              </span>
              <span className="mt-1 block text-sm font-medium text-ink">{s.label}</span>
              {s.detail && <span className="mt-0.5 block text-xs text-ink-3">{s.detail}</span>}
            </>
          );
          return (
            <li
              key={s.key}
              aria-current={s.state === "current" ? "step" : undefined}
              className={cx("border-b border-r border-line", s.state === "current" ? "bg-accent-subtle/60" : "bg-surface")}
            >
              {s.href ? (
                <Link
                  href={s.href}
                  className="block h-full px-3 py-2.5 hover:bg-surface-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
                >
                  {body}
                </Link>
              ) : (
                <div className="h-full px-3 py-2.5">{body}</div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ----------------------------------------------------------------------------- tables: sort & filter

export type SortDir = "asc" | "desc";
export interface SortState<K extends string> {
  key: K;
  dir: SortDir;
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

/** Compares two cell values; empty values always sort last regardless of direction. */
function compareValues(a: unknown, b: unknown, dir: SortDir): number {
  if (isEmpty(a) || isEmpty(b)) return isEmpty(a) === isEmpty(b) ? 0 : isEmpty(a) ? 1 : -1;
  const c =
    typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return dir === "asc" ? c : -c;
}

/** Client-side sorting over already-loaded rows. */
export function useSortedRows<T, K extends string>(
  rows: T[],
  accessors: Record<K, (row: T) => unknown>,
  initial: SortState<K>,
) {
  const [sort, setSort] = useState<SortState<K>>(initial);
  const accessorsRef = useRef(accessors);
  accessorsRef.current = accessors;
  const sorted = useMemo(() => {
    const get = accessorsRef.current[sort.key];
    return [...rows].sort((x, y) => compareValues(get(x), get(y), sort.dir));
  }, [rows, sort]);
  const toggle = (key: K) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  return { rows: sorted, sort, toggle };
}

/** Sortable column header: a button inside the th with aria-sort on the th. */
export function SortTh<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  numeric,
}: {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onSort: (k: K) => void;
  numeric?: boolean;
}) {
  const active = sort.key === sortKey;
  return (
    <th
      className={numeric ? thNum : th}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      scope="col"
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cx(
          "inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink focus-visible:outline-2 focus-visible:outline-accent",
          active && "text-ink",
        )}
      >
        {label}
        <span aria-hidden="true" className="text-[10px]">
          {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

/** Compact search input for filtering a table. */
export function FilterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-ink-3">
        {label}
      </label>
      <input
        id={id}
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full min-w-48 rounded-sm border border-line-strong bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-2 focus:outline-accent"
      />
    </div>
  );
}

/** Compact select for filtering a table. */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-ink-3">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="block rounded-sm border border-line-strong bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-2 focus:outline-accent"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "danger" | "success" }) {
  return (
    <div className="border-t border-ink/80 pt-2">
      <p className="text-xs font-medium text-ink-3">{label}</p>
      <p
        className={cx(
          "mt-0.5 text-base font-semibold tabular-nums",
          tone === "danger" ? "text-risk" : tone === "success" ? "text-accent" : "text-ink",
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
    <div className="overflow-x-auto rounded-md border border-line bg-surface" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export const th = "whitespace-nowrap border-b border-line bg-surface-muted px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-3";
export const thNum = cx(th, "text-right");
export const td = "px-3 py-2 align-top text-sm text-ink";
export const tdNum = "px-3 py-2 align-top text-right text-sm tabular-nums whitespace-nowrap text-ink";
export const tableClass = "min-w-full divide-y divide-line";
export const tbodyClass = "divide-y divide-line";

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
  "block w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-slate-400 focus:border-accent focus:outline-2 focus:outline-accent disabled:bg-surface-muted aria-[invalid=true]:border-risk";

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
          className="h-4 w-4 rounded border-slate-400 accent-[#2f6b4f] focus:outline-2 focus:outline-accent"
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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/30 p-0 sm:items-center sm:p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-sm border border-line bg-surface sm:max-w-lg sm:rounded-sm"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id={titleId} className="font-display text-lg text-ink">
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
