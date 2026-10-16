"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  ErrorState,
  LoadingBlock,
  Pagination,
  SelectField,
  TableWrap,
  TextAreaField,
  TextField,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDateTime, humanize } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import { FUND_TYPES, type FundDetail, type FundUpdate } from "@/lib/types";
import { parseAliases, validateFund } from "./FundLibrary";
import { FundDocuments } from "./FundDocuments";
import { FundTerms } from "./FundTerms";
import { FundStatusBadge, MetadataStatusBadge, canReviewLibrary, fundTypeLabel } from "./shared";

const AUDIT_LIMIT = 20;

function EditFundDialog({ fund, onClose, onSaved }: { fund: FundDetail; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({
    name: fund.name,
    fund_type: fund.fund_type,
    issuer: fund.issuer ?? "",
    ticker: fund.ticker ?? "",
    share_class: fund.share_class ?? "",
    sec_cik: fund.sec_cik ?? "",
    aliases: fund.aliases.join(", "),
    description: fund.description ?? "",
    metadata_status: fund.metadata_status,
    status: fund.status,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV((p) => ({ ...p, [k]: e.target.value }));
  const opt = (s: string) => (s.trim() ? s.trim() : null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs = validateFund(v);
    setErrors(errs);
    setError(null);
    if (Object.keys(errs).length) return;
    const body: FundUpdate = {
      name: v.name.trim(),
      fund_type: v.fund_type,
      issuer: opt(v.issuer),
      ticker: opt(v.ticker),
      share_class: opt(v.share_class),
      sec_cik: opt(v.sec_cik),
      aliases: parseAliases(v.aliases),
      description: opt(v.description),
      metadata_status: v.metadata_status,
      status: v.status,
    };
    setSaving(true);
    try {
      await endpoints.updateFund(fund.id, body);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      title="Edit fund details"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="edit-fund-form" loading={saving}>
            Save
          </Button>
        </>
      }
    >
      <form id="edit-fund-form" onSubmit={submit} noValidate className="space-y-3">
        {error ? <ErrorState error={error} /> : null}
        <TextField label="Name" required value={v.name} onChange={set("name")} error={errors.name} />
        <SelectField
          label="Fund type"
          value={v.fund_type}
          onChange={set("fund_type")}
          error={errors.fund_type}
          options={FUND_TYPES.map((t) => ({ value: t, label: fundTypeLabel(t) }))}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Issuer / sponsor" value={v.issuer} onChange={set("issuer")} error={errors.issuer} />
          <TextField label="Ticker" value={v.ticker} onChange={set("ticker")} error={errors.ticker} />
          <TextField label="Share class" value={v.share_class} onChange={set("share_class")} error={errors.share_class} />
          <TextField label="SEC CIK" inputMode="numeric" value={v.sec_cik} onChange={set("sec_cik")} error={errors.sec_cik} />
        </div>
        <TextField label="Aliases" value={v.aliases} onChange={set("aliases")} hint="Separated by commas." />
        <TextAreaField label="Description" value={v.description} onChange={set("description")} />
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label="Metadata status"
            value={v.metadata_status}
            onChange={set("metadata_status")}
            options={[
              { value: "needs_review", label: "Needs review" },
              { value: "verified", label: "Verified" },
            ]}
          />
          <SelectField
            label="Status"
            value={v.status}
            onChange={set("status")}
            options={[
              { value: "active", label: "Active" },
              { value: "archived", label: "Archived" },
            ]}
          />
        </div>
      </form>
    </Dialog>
  );
}

function FundAudit({ fundId }: { fundId: string }) {
  const [offset, setOffset] = useState(0);
  const q = useApiQuery(() => endpoints.fundAudit(fundId, { limit: AUDIT_LIMIT, offset }), [fundId, offset]);
  if (q.loading && !q.data) return <LoadingBlock rows={2} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  if (q.data.items.length === 0) return <p className="text-sm text-ink-3">No audit events yet.</p>;
  return (
    <>
      <TableWrap label="Fund audit events">
        <table className={tableClass}>
          <thead>
            <tr>
              <th className={th}>When</th>
              <th className={th}>Action</th>
              <th className={th}>Entity</th>
              <th className={th}>Details</th>
            </tr>
          </thead>
          <tbody className={tbodyClass}>
            {q.data.items.map((a) => (
              <tr key={a.id}>
                <td className={td}>{formatDateTime(a.created_at)}</td>
                <td className={td}>{a.action}</td>
                <td className={td}>{humanize(a.entity_type)}</td>
                <td className={td}>
                  <code className="break-all text-xs text-ink-3">
                    {Object.keys(a.details).length ? JSON.stringify(a.details) : EMPTY}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <Pagination total={q.data.total} limit={q.data.limit || AUDIT_LIMIT} offset={q.data.offset} onChange={setOffset} />
    </>
  );
}

export function FundDetailView({ fundId }: { fundId: string }) {
  const toast = useToast();
  const q = useApiQuery(() => endpoints.getFund(fundId), [fundId]);
  const [editing, setEditing] = useState(false);

  if (q.loading && !q.data) return <LoadingBlock rows={6} label="Loading fund…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  const f = q.data;
  const canReview = canReviewLibrary(f.your_role);

  const meta: Array<[string, string]> = [
    ["Type", fundTypeLabel(f.fund_type)],
    ["Issuer / sponsor", f.issuer ?? EMPTY],
    ["Ticker", f.ticker ?? EMPTY],
    ["Share class", f.share_class ?? EMPTY],
    ["SEC CIK", f.sec_cik ?? EMPTY],
    ["Aliases", f.aliases.length ? f.aliases.join(", ") : EMPTY],
    ["Updated", formatDateTime(f.updated_at)],
  ];

  return (
    <div className="space-y-5">
      <div className="border-b border-line pb-4">
        <nav aria-label="Breadcrumb" className="text-xs text-ink-3">
          <Link href="/funds" className="hover:underline">
            Fund Library
          </Link>{" "}
          / <span className="text-ink">{f.name}</span>
        </nav>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="font-display text-[1.75rem] leading-tight text-ink">{f.name}</h1>
          <Badge>{fundTypeLabel(f.fund_type)}</Badge>
          <MetadataStatusBadge status={f.metadata_status} />
          <FundStatusBadge status={f.status} />
          <Badge tone="info">Your role: {f.your_role}</Badge>
        </div>
        {f.description && <p className="mt-2 max-w-3xl text-sm text-ink-2">{f.description}</p>}
      </div>

      <Card
        title="Fund details"
        actions={
          canReview ? (
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              Edit details
            </Button>
          ) : undefined
        }
      >
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {meta.map(([k, val]) => (
            <div key={k}>
              <dt className="text-ink-3">{k}</dt>
              <dd className="text-ink">{val}</dd>
            </div>
          ))}
        </dl>
        {!canReview && (
          <p className="mt-3 text-xs text-ink-3">Only firm reviewers and admins can edit fund details.</p>
        )}
      </Card>

      <FundTerms fundId={f.id} canReview={canReview} />

      <FundDocuments fundId={f.id} documents={f.documents} canReview={canReview} onChanged={() => void q.reload()} />

      <Card title={`Linked holdings (${f.linked_holdings_total})`}>
        {f.linked_holdings.length === 0 ? (
          <p className="text-sm text-ink-3">
            {f.linked_holdings_total > 0
              ? "Holdings are linked to this fund in households you do not have access to."
              : "No household holdings are linked to this fund yet. Link one from a household's Profile → Assets."}
          </p>
        ) : (
          <>
            <TableWrap label="Linked holdings">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>Holding</th>
                    <th className={th}>Household</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {f.linked_holdings.map((h) => (
                    <tr key={h.asset_id}>
                      <td className={td}>{h.asset_name}</td>
                      <td className={td}>
                        <Link href={`/households/${h.household_id}/profile`} className="underline-offset-2 hover:underline">
                          {h.household_name}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            {f.linked_holdings_total > f.linked_holdings.length && (
              <p className="mt-2 text-xs text-ink-3">
                {f.linked_holdings_total - f.linked_holdings.length} more in households you do not have access to.
              </p>
            )}
          </>
        )}
      </Card>

      <Card title="Audit trail">
        <FundAudit fundId={f.id} />
      </Card>

      {editing && (
        <EditFundDialog
          fund={f}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            toast.success("Fund updated");
            void q.reload();
          }}
        />
      )}
    </div>
  );
}
