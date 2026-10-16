"use client";

import { Fragment, useMemo, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  ErrorState,
  LoadingBlock,
  Notice,
  SelectField,
  TableWrap,
  TextField,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import {
  AmbiguousBadge,
  QuoteVerifiedBadge,
  ReviewStatusBadge,
  ValidationIssuesBadge,
  ValueKindBadge,
} from "@/components/badges";
import { EditForm, PageTextPanel } from "@/components/constraints/ConstraintReview";
import { ConstraintValue } from "@/components/constraints/shared";
import { useReviewCount } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDate, humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { ConstraintOut, ConstraintSupersede } from "@/lib/types";
import { todayIso } from "./shared";

const APPROVED = new Set(["confirmed", "edited"]);
const CONFLICT_MESSAGE = "Someone else changed this term while you were reviewing it. The latest version has been loaded.";

export function isApproved(c: Pick<ConstraintOut, "review_status">): boolean {
  return APPROVED.has(c.review_status);
}

/** Older approved terms the given (approved) term may supersede: same type and asset, not already superseded. */
export function supersedeCandidates(term: ConstraintOut, all: ConstraintOut[]): ConstraintOut[] {
  return all.filter(
    (o) =>
      o.id !== term.id &&
      o.constraint_type === term.constraint_type &&
      o.asset_key === term.asset_key &&
      isApproved(o) &&
      !o.superseded_by_id,
  );
}

function describeTerm(c: ConstraintOut): string {
  const val = c.value !== null ? `${c.value}${c.unit ? ` ${c.unit}` : ""}` : "qualitative";
  return `${val} · ${c.document_name} p.${c.pdf_page}${c.effective_from ? ` · from ${c.effective_from}` : ""}`;
}

function SupersedeDialog({
  term,
  candidates,
  onClose,
  onDone,
  onConflict,
}: {
  term: ConstraintOut;
  candidates: ConstraintOut[];
  onClose: () => void;
  onDone: () => void;
  onConflict: () => void;
}) {
  const toast = useToast();
  const [olderId, setOlderId] = useState(candidates[0]?.id ?? "");
  const [date, setDate] = useState(term.effective_from ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const older = candidates.find((c) => c.id === olderId);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!older) return;
    const body: ConstraintSupersede = {
      expected_revision: term.revision,
      superseded_id: older.id,
      superseded_expected_revision: older.revision,
    };
    if (date.trim()) body.effective_date = date.trim();
    if (note.trim()) body.note = note.trim();
    setSaving(true);
    setError(null);
    try {
      await endpoints.supersedeConstraint(term.id, body);
      toast.success("Supersession recorded", "The older term still applies before the effective date.");
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "conflict" && /changed/i.test(err.message)) {
        onConflict();
        return;
      }
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      title="Mark as superseding an older term"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="supersede-form" loading={saving} disabled={!older}>
            Record supersession
          </Button>
        </>
      }
    >
      <form id="supersede-form" onSubmit={submit} noValidate className="space-y-3">
        <p>
          Newer term: <strong>{humanize(term.constraint_type)}</strong> — {describeTerm(term)}
        </p>
        {candidates.length === 0 ? (
          <Notice tone="warning">
            There is no other approved, unsuperseded {humanize(term.constraint_type).toLowerCase()} term for this fund.
          </Notice>
        ) : (
          <SelectField
            label="Older term it replaces"
            value={olderId}
            onChange={(e) => setOlderId(e.target.value)}
            options={candidates.map((c) => ({ value: c.id, label: describeTerm(c) }))}
          />
        )}
        <TextField
          label="Effective date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          hint="The first date the newer term applies. Leave empty to use the newer term's start date or its document's effective date."
        />
        <TextField label="Note (optional)" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        <Notice>The older term keeps its history and still applies to any date before the effective date.</Notice>
        {error ? <ErrorState error={error} /> : null}
      </form>
    </Dialog>
  );
}

function EvidenceRow({ term }: { term: ConstraintOut }) {
  return (
    <div className="space-y-3 bg-surface-muted px-4 py-3">
      <blockquote className="evidence-quote border-l-2 border-accent pl-3">“{term.evidence_quote}”</blockquote>
      <p className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
        <span>
          {term.document_name} · PDF page {term.pdf_page}
          {term.printed_page ? ` (printed ${term.printed_page})` : ""}
          {term.document_section ? ` · ${term.document_section}` : ""}
        </span>
        <QuoteVerifiedBadge verified={term.quote_verified} />
        <AmbiguousBadge ambiguous={term.ambiguous} />
        <ValidationIssuesBadge issues={term.validation_issues} />
      </p>
      {term.interpretation && <p className="text-sm text-ink-2">Interpretation: {term.interpretation}</p>}
      <PageTextPanel documentId={term.document_id} page={term.pdf_page} quote={term.evidence_quote} />
    </div>
  );
}

export function FundTerms({ fundId, canReview }: { fundId: string; canReview: boolean }) {
  const toast = useToast();
  const reviewCount = useReviewCount();
  const [asOf, setAsOf] = useState(todayIso());
  const q = useApiQuery(() => endpoints.fundTerms(fundId, asOf || undefined), [fundId, asOf]);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [editing, setEditing] = useState<ConstraintOut | null>(null);
  const [superseding, setSuperseding] = useState<ConstraintOut | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  const applicable = useMemo(() => new Set(q.data?.applicable_ids ?? []), [q.data]);
  const terms = q.data?.terms ?? [];

  const afterChange = async () => {
    await q.reload();
    reviewCount.refresh();
  };

  const handleConflict = async () => {
    setConflict(true);
    setEditing(null);
    setSuperseding(null);
    await q.reload();
  };

  const decide = async (term: ConstraintOut, kind: "approve" | "reject") => {
    setBusy(`${kind}-${term.id}`);
    setConflict(false);
    try {
      const body = { expected_revision: term.revision };
      if (kind === "approve") await endpoints.approveConstraint(term.id, body);
      else await endpoints.rejectConstraint(term.id, body);
      toast.success(kind === "approve" ? "Term approved" : "Term rejected");
      await afterChange();
    } catch (e) {
      if (e instanceof ApiError && e.isConflict) await handleConflict();
      else {
        const d = describeError(e);
        toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title="Terms"
      actions={
        <div className="w-44">
          <TextField label="In force on" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </div>
      }
    >
      <div className="space-y-3">
        <Notice>
          Library terms affect simulations only after a reviewer approves them. A simulation uses the approved terms in
          force on its as-of date: a superseded term still applies before its end date.
          {!canReview && " You can read these terms; reviewers and admins approve, edit and supersede them."}
        </Notice>
        {conflict && (
          <div role="alert">
            <Notice tone="warning" title="Updated by someone else">
              {CONFLICT_MESSAGE}
            </Notice>
          </div>
        )}
        {q.loading && !q.data ? (
          <LoadingBlock rows={4} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.reload()} />
        ) : terms.length === 0 ? (
          <p className="text-sm text-ink-3">No terms have been extracted from this fund&apos;s documents yet.</p>
        ) : (
          <TableWrap label="Fund terms">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Type</th>
                  <th className={thNum}>Value</th>
                  <th className={th}>Value kind</th>
                  <th className={th}>Effective from</th>
                  <th className={th}>Effective to</th>
                  <th className={th}>Superseded by</th>
                  <th className={th}>Review</th>
                  <th className={th}>In force {q.data?.as_of ? `on ${formatDate(q.data.as_of)}` : ""}</th>
                  <th className={th}>Source</th>
                  <th className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {terms.map((t) => {
                  const inForce = applicable.has(t.id);
                  const supersededBy = t.superseded_by_id ? terms.find((x) => x.id === t.superseded_by_id) : undefined;
                  const label = humanize(t.constraint_type);
                  return (
                    <Fragment key={t.id}>
                      <tr>
                        <td className={td}>
                          <span className="font-medium">{label}</span>
                          <span className="block text-xs text-ink-3">{humanize(t.asset_key)}</span>
                        </td>
                        <td className={tdNum}>
                          <ConstraintValue c={t} />
                        </td>
                        <td className={td}>{t.value_kind ? <ValueKindBadge valueKind={t.value_kind} /> : EMPTY}</td>
                        <td className={td}>{t.effective_from ? formatDate(t.effective_from) : EMPTY}</td>
                        <td className={td}>{t.effective_to ? formatDate(t.effective_to) : EMPTY}</td>
                        <td className={td}>
                          {t.superseded_by_id ? (
                            <span className="text-xs">
                              {supersededBy ? describeTerm(supersededBy) : <code>{t.superseded_by_id.slice(0, 8)}</code>}
                            </span>
                          ) : (
                            EMPTY
                          )}
                        </td>
                        <td className={td}>
                          <ReviewStatusBadge status={t.review_status} />
                        </td>
                        <td className={td}>
                          {inForce ? (
                            <Badge tone="success" title="Approved and in force on the selected date">
                              In force
                            </Badge>
                          ) : (
                            <span className="text-xs text-ink-3">{isApproved(t) ? "Not on this date" : "Not approved"}</span>
                          )}
                        </td>
                        <td className={td}>
                          <span className="break-all text-xs">{t.document_name}</span>
                          <span className="block text-xs text-ink-3">p. {t.pdf_page}</span>
                        </td>
                        <td className={td}>
                          <div className="flex flex-wrap gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-expanded={openEvidence === t.id}
                              aria-label={`Evidence for ${label}, page ${t.pdf_page}`}
                              onClick={() => setOpenEvidence(openEvidence === t.id ? null : t.id)}
                            >
                              Evidence
                            </Button>
                            {canReview && (
                              <>
                                {t.review_status !== "confirmed" && (
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    aria-label={`Approve ${label}, page ${t.pdf_page}`}
                                    loading={busy === `approve-${t.id}`}
                                    disabled={busy !== null}
                                    onClick={() => decide(t, "approve")}
                                  >
                                    Approve
                                  </Button>
                                )}
                                {t.review_status !== "rejected" && (
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    aria-label={`Reject ${label}, page ${t.pdf_page}`}
                                    loading={busy === `reject-${t.id}`}
                                    disabled={busy !== null}
                                    onClick={() => decide(t, "reject")}
                                  >
                                    Reject
                                  </Button>
                                )}
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  aria-label={`Edit ${label}, page ${t.pdf_page}`}
                                  disabled={busy !== null}
                                  onClick={() => setEditing(t)}
                                >
                                  Edit
                                </Button>
                                {isApproved(t) && !t.superseded_by_id && (
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    aria-label={`Supersede an older term with ${label}, page ${t.pdf_page}`}
                                    disabled={busy !== null}
                                    onClick={() => setSuperseding(t)}
                                  >
                                    Supersede
                                  </Button>
                                )}
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                      {openEvidence === t.id && (
                        <tr>
                          <td colSpan={10} className="p-0">
                            <EvidenceRow term={t} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
      </div>

      {editing && (
        <Dialog open title={`Edit ${humanize(editing.constraint_type)}`} onClose={() => setEditing(null)}>
          <EditForm
            constraint={editing}
            onCancel={() => setEditing(null)}
            onConflict={() => void handleConflict()}
            onSaved={() => {
              setEditing(null);
              toast.success("Term updated");
              void afterChange();
            }}
          />
        </Dialog>
      )}
      {superseding && (
        <SupersedeDialog
          term={superseding}
          candidates={supersedeCandidates(superseding, terms)}
          onClose={() => setSuperseding(null)}
          onConflict={() => void handleConflict()}
          onDone={() => {
            setSuperseding(null);
            void afterChange();
          }}
        />
      )}
    </Card>
  );
}
