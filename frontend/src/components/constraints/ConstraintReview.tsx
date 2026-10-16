"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  LoadingBlock,
  Notice,
  SelectField,
  TextAreaField,
  TextField,
} from "@/components/ui";
import {
  AmbiguousBadge,
  ConfidenceBadge,
  QuoteVerifiedBadge,
  ReviewStatusBadge,
  SourceTypeBadge,
  VALUE_KIND_INFO,
  ValidationIssuesBadge,
  ValueKindBadge,
} from "@/components/badges";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, formatNumber, humanize, normalizeDecimalInput } from "@/lib/format";
import { highlightQuote } from "@/lib/highlight";
import { describeError, useApiQuery } from "@/lib/hooks";
import { VALUE_KINDS, type ConstraintDetail, type ConstraintOut, type ConstraintUpdate, type ValueKind } from "@/lib/types";
import { ConstraintValue, isQualitative } from "./shared";

const DECIMAL_RE = /^-?\d+(\.\d+)?$/;
const CONFLICT_MESSAGE =
  "Someone else changed this constraint while you were reviewing it. The latest version has been loaded; please review it and try again.";

export function PageTextPanel({ documentId, page, quote }: { documentId: string; page: number; quote: string }) {
  const q = useApiQuery(() => endpoints.documentPage(documentId, page), [documentId, page]);
  if (q.loading && !q.data) return <LoadingBlock rows={4} label="Loading page text…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const { segments, found } = highlightQuote(q.data.text, quote);
  return (
    <div className="space-y-2">
      <p className="flex flex-wrap gap-2 text-xs text-slate-600">
        <span>PDF page {q.data.pdf_page}</span>
        {q.data.printed_page && <span>· printed page {q.data.printed_page}</span>}
        {q.data.section && <span>· {q.data.section}</span>}
        {q.data.ocr && <Badge tone="warning">OCR text</Badge>}
        {!found && <Badge tone="warning">Quote not found on this page</Badge>}
      </p>
      <div className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-800">
        {segments.map((s, i) => (s.match ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>))}
      </div>
    </div>
  );
}

interface EditValues {
  value: string;
  lower_bound: string;
  upper_bound: string;
  unit: string;
  timing: string;
  conditions: string;
  interpretation: string;
  value_kind: string;
  /** One exception per line. */
  exceptions: string;
  discretion: string;
  effective_period: string;
  effective_from: string;
  effective_to: string;
  note: string;
}

const MAX_EXCEPTIONS = 20;

function exceptionList(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

const MAXIMUM_NOTE =
  "A maximum is a limit, not a guaranteed payout: the counterparty may fill less than this, or nothing, and the simulation treats it that way.";

function initialValues(c: ConstraintOut): EditValues {
  return {
    value: c.value ?? "",
    lower_bound: c.lower_bound ?? "",
    upper_bound: c.upper_bound ?? "",
    unit: c.unit ?? "",
    timing: c.timing ?? "",
    conditions: c.conditions ?? "",
    interpretation: c.interpretation ?? "",
    value_kind: c.value_kind ?? "",
    exceptions: (c.exceptions ?? []).join("\n"),
    discretion: c.discretion ?? "",
    effective_period: c.effective_period ?? "",
    effective_from: c.effective_from ?? "",
    effective_to: c.effective_to ?? "",
    note: "",
  };
}

export function EditForm({
  constraint,
  onSaved,
  onConflict,
  onCancel,
}: {
  constraint: ConstraintOut;
  onSaved: (c: ConstraintDetail) => void;
  onConflict: () => void;
  onCancel: () => void;
}) {
  const qualitative = isQualitative(constraint);
  const [v, setV] = useState<EditValues>(() => initialValues(constraint));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof EditValues) => (e: { target: { value: string } }) => setV((p) => ({ ...p, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const body: ConstraintUpdate = { expected_revision: constraint.revision };
    const orig = initialValues(constraint);
    if (!qualitative) {
      for (const k of ["value", "lower_bound", "upper_bound"] as const) {
        const raw = normalizeDecimalInput(v[k]);
        if (raw && !DECIMAL_RE.test(raw)) errs[k] = "Enter a number.";
        else if (raw !== normalizeDecimalInput(orig[k])) body[k] = raw ? raw : null;
      }
      const lo = Number(normalizeDecimalInput(v.lower_bound));
      const hi = Number(normalizeDecimalInput(v.upper_bound));
      if (v.lower_bound.trim() && v.upper_bound.trim() && !errs.lower_bound && !errs.upper_bound && lo > hi) {
        errs.upper_bound = "Upper bound must be at least the lower bound.";
      }
    }
    for (const k of ["unit", "timing", "conditions", "interpretation"] as const) {
      if (v[k].trim() !== orig[k].trim()) body[k] = v[k].trim() ? v[k].trim() : null;
    }
    for (const k of ["discretion", "effective_period"] as const) {
      if (v[k].trim() !== orig[k].trim()) body[k] = v[k].trim() ? v[k].trim() : null;
    }
    for (const k of ["effective_from", "effective_to"] as const) {
      const val = v[k].trim();
      if (val && !/^\d{4}-\d{2}-\d{2}$/.test(val)) errs[k] = "Use the format YYYY-MM-DD.";
      else if (val !== orig[k]) body[k] = val || null;
    }
    if (v.effective_from && v.effective_to && !errs.effective_from && !errs.effective_to && v.effective_to < v.effective_from) {
      errs.effective_to = "The end date must be on or after the start date.";
    }
    if (v.value_kind !== orig.value_kind) body.value_kind = v.value_kind ? (v.value_kind as ValueKind) : null;
    const exceptions = exceptionList(v.exceptions);
    if (exceptions.join("\n") !== exceptionList(orig.exceptions).join("\n")) body.exceptions = exceptions;
    if (exceptions.length > MAX_EXCEPTIONS) errs.exceptions = `List at most ${MAX_EXCEPTIONS} exceptions.`;
    if (v.discretion.length > 2000) errs.discretion = "Use at most 2000 characters.";
    if (v.effective_period.length > 160) errs.effective_period = "Use at most 160 characters.";
    if (v.unit.length > 80) errs.unit = "Use at most 80 characters.";
    if (v.timing.length > 160) errs.timing = "Use at most 160 characters.";
    if (v.note.length > 500) errs.note = "Use at most 500 characters.";
    setErrors(errs);
    setFormError(null);
    if (Object.keys(errs).length) return;
    if (Object.keys(body).length === 1) {
      setFormError(new Error("No changes to save."));
      return;
    }
    if (v.note.trim()) body.note = v.note.trim();
    setSaving(true);
    try {
      const updated = await endpoints.updateConstraint(constraint.id, body);
      onSaved(updated);
    } catch (err) {
      if (err instanceof ApiError && err.isConflict) {
        onConflict();
        return;
      }
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setFormError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      {formError ? <ErrorState error={formError} /> : null}
      {qualitative ? (
        <Notice>
          This is a qualitative constraint: it has no numeric value. You can refine its wording below, but numeric values
          cannot be added.
        </Notice>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          <TextField label="Value" inputMode="decimal" value={v.value} onChange={set("value")} error={errors.value} />
          <TextField label="Lower bound" inputMode="decimal" value={v.lower_bound} onChange={set("lower_bound")} error={errors.lower_bound} />
          <TextField label="Upper bound" inputMode="decimal" value={v.upper_bound} onChange={set("upper_bound")} error={errors.upper_bound} />
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label="Unit" value={v.unit} onChange={set("unit")} error={errors.unit} maxLength={80} />
        <TextField label="Timing" value={v.timing} onChange={set("timing")} error={errors.timing} maxLength={160} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label="Value kind"
          value={v.value_kind}
          onChange={set("value_kind")}
          error={errors.value_kind}
          hint={v.value_kind ? VALUE_KIND_INFO[v.value_kind]?.title : "How the number in the clause should be read."}
          options={[{ value: "", label: "Not set" }, ...VALUE_KINDS.map((k) => ({ value: k, label: VALUE_KIND_INFO[k]?.label ?? humanize(k) }))]}
        />
        <TextField
          label="Effective period"
          value={v.effective_period}
          onChange={set("effective_period")}
          error={errors.effective_period}
          maxLength={160}
          hint="When the term applies, e.g. “after the first anniversary”."
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="Effective from"
          type="date"
          value={v.effective_from}
          onChange={set("effective_from")}
          error={errors.effective_from}
          hint="First date the term applies. Empty = no start limit."
        />
        <TextField
          label="Effective to"
          type="date"
          value={v.effective_to}
          onChange={set("effective_to")}
          error={errors.effective_to}
          hint="Last date the term applies. Empty = open-ended."
        />
      </div>
      <TextAreaField label="Conditions" value={v.conditions} onChange={set("conditions")} error={errors.conditions} maxLength={4000} />
      <TextAreaField
        label="Exceptions"
        value={v.exceptions}
        onChange={set("exceptions")}
        error={errors.exceptions}
        hint={`One per line (at most ${MAX_EXCEPTIONS}).`}
      />
      <TextAreaField
        label="Discretion"
        value={v.discretion}
        onChange={set("discretion")}
        error={errors.discretion}
        maxLength={2000}
        hint="Any discretion the counterparty keeps, e.g. the board may suspend or limit repurchases."
      />
      <TextAreaField label="Interpretation" value={v.interpretation} onChange={set("interpretation")} error={errors.interpretation} maxLength={4000} />
      <TextField label="Review note (optional)" value={v.note} onChange={set("note")} error={errors.note} maxLength={500} hint="Recorded in the revision history." />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={saving}>
          Save edits
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function ConstraintReview({
  constraintId,
  householdId,
  canEdit,
}: {
  constraintId: string;
  householdId: string;
  canEdit: boolean;
}) {
  const toast = useToast();
  const q = useApiQuery(() => endpoints.getConstraint(constraintId), [constraintId]);
  const [editing, setEditing] = useState(false);
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");
  const [conflict, setConflict] = useState(false);
  const [viewPage, setViewPage] = useState<number | null>(null);

  const handleConflict = async () => {
    setConflict(true);
    setEditing(false);
    toast.error("This constraint was changed by someone else", "The latest version has been loaded.");
    await q.reload();
  };

  const decide = async (kind: "approve" | "reject") => {
    if (!q.data) return;
    setDeciding(kind);
    setConflict(false);
    const body = { expected_revision: q.data.revision, note: note.trim() ? note.trim() : null };
    try {
      const updated =
        kind === "approve"
          ? await endpoints.approveConstraint(q.data.id, body)
          : await endpoints.rejectConstraint(q.data.id, body);
      if (updated && typeof updated === "object" && "id" in updated) q.setData(updated);
      else await q.reload();
      setNote("");
      toast.success(kind === "approve" ? "Constraint approved" : "Constraint rejected");
    } catch (e) {
      if (e instanceof ApiError && e.isConflict) await handleConflict();
      else {
        const d = describeError(e);
        toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      }
    } finally {
      setDeciding(null);
    }
  };

  if (q.loading && !q.data) return <LoadingBlock rows={6} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const c = q.data;
  const pages = [c.pdf_page, ...c.corroborating_pages.filter((p) => p !== c.pdf_page)];
  const issues = c.validation_issues ?? [];
  const exceptions = c.exceptions ?? [];

  return (
    <div className="space-y-5">
      <div>
        <Link href={`/households/${householdId}/constraints`} className="text-xs text-slate-600 hover:underline">
          ← Terms
        </Link>
        <h2 className="font-display mt-1 text-[1.35rem] leading-snug text-ink">{humanize(c.constraint_type)}</h2>
        <p className="text-sm text-slate-700">{c.description}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <ReviewStatusBadge status={c.review_status} />
          <SourceTypeBadge sourceType={c.source_type} />
          <QuoteVerifiedBadge verified={c.quote_verified} />
          <ConfidenceBadge confidence={c.confidence} />
          <ValueKindBadge valueKind={c.value_kind} />
          <AmbiguousBadge ambiguous={c.ambiguous} />
          <ValidationIssuesBadge issues={c.validation_issues} />
          <Badge>Revision {c.revision}</Badge>
        </div>
      </div>

      {conflict && (
        <div role="alert">
          <Notice tone="warning" title="Updated by someone else">
            {CONFLICT_MESSAGE}
          </Notice>
        </div>
      )}
      {issues.length > 0 && (
        <Notice tone={issues.some((i) => i.severity === "error") ? "danger" : "warning"} title="Automated validation warnings">
          <ul className="list-disc space-y-1 pl-5">
            {issues.map((i, idx) => (
              <li key={`${i.code}-${idx}`}>
                {i.severity && <span className="font-medium">{humanize(i.severity)}: </span>}
                {i.message} <code className="text-xs text-slate-600">{i.code}</code>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs">These checks never change a value. Compare the value with the quoted clause before approving.</p>
        </Notice>
      )}
      {c.ambiguous && (
        <Notice tone="warning" title="Ambiguous clause">
          The clause contains discretion or conditions that may not be fully captured. Check the conditions, exceptions and
          discretion fields against the evidence.
        </Notice>
      )}
      {c.source_type === "synthetic_document" && (
        <Notice tone="warning">This constraint comes from a synthetic demo document, not a real contract.</Notice>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Evidence">
          <blockquote className="evidence-quote border-l-2 border-accent bg-surface-muted px-4 py-3">
            “{c.evidence_quote}”
          </blockquote>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div className="col-span-2">
              <dt className="text-slate-600">Document</dt>
              <dd>
                <Link
                  href={c.fund_id ? `/funds/${c.fund_id}` : `/households/${householdId}/documents/${c.document_id}`}
                  className="break-all underline"
                >
                  {c.document_name || "View document"}
                </Link>
              </dd>
            </div>
            <div>
              <dt className="text-slate-600">PDF page</dt>
              <dd className="tabular-nums">{c.pdf_page}</dd>
            </div>
            <div>
              <dt className="text-slate-600">Printed page</dt>
              <dd>{c.printed_page ?? EMPTY}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-slate-600">Section</dt>
              <dd>{c.document_section ?? EMPTY}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-slate-600">Corroborating pages</dt>
              <dd>{c.corroborating_pages.length ? c.corroborating_pages.join(", ") : EMPTY}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-slate-600">Extraction</dt>
              <dd>
                {humanize(c.extraction_method)}
                {c.model ? ` · ${c.model}` : ""}
              </dd>
            </div>
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            {pages.map((p) => (
              <Button
                key={p}
                size="sm"
                variant={viewPage === p ? "primary" : "secondary"}
                aria-pressed={viewPage === p}
                onClick={() => setViewPage(viewPage === p ? null : p)}
              >
                View page {p} text
              </Button>
            ))}
          </div>
        </Card>

        <Card title="Extracted terms">
          {editing ? (
            <EditForm
              constraint={c}
              onCancel={() => setEditing(false)}
              onConflict={() => void handleConflict()}
              onSaved={(updated) => {
                q.setData(updated);
                setEditing(false);
                toast.success("Constraint updated");
              }}
            />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div>
                  <dt className="text-slate-600">Value</dt>
                  <dd>
                    <ConstraintValue c={c} />
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-600">Original extracted value</dt>
                  <dd className="tabular-nums">{c.original_value !== null ? formatNumber(c.original_value, 4) : EMPTY}</dd>
                </div>
                <div>
                  <dt className="text-slate-600">Bounds</dt>
                  <dd className="tabular-nums">
                    {c.lower_bound !== null || c.upper_bound !== null
                      ? `${c.lower_bound !== null ? formatNumber(c.lower_bound, 4) : EMPTY} – ${c.upper_bound !== null ? formatNumber(c.upper_bound, 4) : EMPTY}`
                      : EMPTY}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-600">Unit</dt>
                  <dd>{c.unit ?? EMPTY}</dd>
                </div>
                <div>
                  <dt className="text-slate-600">Asset</dt>
                  <dd>{c.asset_key}</dd>
                </div>
                <div>
                  <dt className="text-slate-600">Timing</dt>
                  <dd>{c.timing ?? EMPTY}</dd>
                </div>
                <div>
                  <dt className="text-slate-600">Value kind</dt>
                  <dd>{c.value_kind ? <ValueKindBadge valueKind={c.value_kind} /> : EMPTY}</dd>
                </div>
                <div>
                  <dt className="text-slate-600">Effective period</dt>
                  <dd>{c.effective_period ?? EMPTY}</dd>
                </div>
                {c.value_kind === "maximum" && (
                  <div className="col-span-2">
                    <Notice>{MAXIMUM_NOTE}</Notice>
                  </div>
                )}
                <div className="col-span-2">
                  <dt className="text-slate-600">Conditions</dt>
                  <dd className="whitespace-pre-wrap">{c.conditions ?? EMPTY}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-slate-600">Exceptions</dt>
                  <dd>
                    {exceptions.length ? (
                      <ul className="list-disc space-y-0.5 pl-5">
                        {exceptions.map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      EMPTY
                    )}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-slate-600">Discretion</dt>
                  <dd className="whitespace-pre-wrap">{c.discretion ?? EMPTY}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-slate-600">Interpretation</dt>
                  <dd className="whitespace-pre-wrap">{c.interpretation || EMPTY}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-slate-600">Reviewed</dt>
                  <dd>
                    {formatDateTime(c.reviewed_at)}
                    {c.reviewed_by && (
                      <span className="ml-1 font-mono text-xs text-slate-500" title="Reviewer user ID">
                        by {c.reviewed_by}
                      </span>
                    )}
                  </dd>
                </div>
              </dl>
              {canEdit && (
                <div className="mt-4 space-y-3 border-t border-slate-200 pt-4">
                  <TextField label="Decision note (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
                  <div className="flex flex-wrap gap-2">
                    <Button variant="accent" onClick={() => decide("approve")} loading={deciding === "approve"} disabled={deciding !== null}>
                      Approve
                    </Button>
                    <Button variant="danger" onClick={() => decide("reject")} loading={deciding === "reject"} disabled={deciding !== null}>
                      Reject
                    </Button>
                    <Button variant="secondary" onClick={() => setEditing(true)} disabled={deciding !== null}>
                      Edit
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      {viewPage !== null && (
        <Card title={`Page ${viewPage} text`} actions={<Button size="sm" variant="ghost" onClick={() => setViewPage(null)}>Close</Button>}>
          <PageTextPanel documentId={c.document_id} page={viewPage} quote={c.evidence_quote} />
        </Card>
      )}

      <Card title="Revision history">
        {c.revisions.length === 0 ? (
          <p className="text-sm text-slate-600">No revisions recorded.</p>
        ) : (
          <ol className="space-y-3">
            {[...c.revisions]
              .sort((a, b) => b.revision - a.revision)
              .map((r) => (
                <li key={r.revision} className="rounded-md border border-slate-200 p-3 text-sm">
                  <p className="flex flex-wrap items-center gap-2">
                    <Badge>Revision {r.revision}</Badge>
                    <span className="text-slate-600">{formatDateTime(r.created_at)}</span>
                    {r.changed_by && <span className="font-mono text-xs text-slate-500">{r.changed_by}</span>}
                  </p>
                  {Object.keys(r.change).length > 0 && (
                    <ul className="mt-2 space-y-0.5">
                      {Object.entries(r.change).map(([k, val]) => (
                        <li key={k}>
                          <span className="text-slate-600">{humanize(k)}:</span>{" "}
                          <code className="break-all text-xs">{typeof val === "string" ? val : JSON.stringify(val)}</code>
                        </li>
                      ))}
                    </ul>
                  )}
                  {r.note && <p className="mt-1 text-slate-700">Note: {r.note}</p>}
                </li>
              ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
