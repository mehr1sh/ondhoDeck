"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import {
  Button,
  CheckboxField,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  PageHeader,
  Pagination,
  SelectField,
  TableWrap,
  TextAreaField,
  TextField,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY } from "@/lib/format";
import { useApiQuery } from "@/lib/hooks";
import { FUND_TYPES, type FundIn, type FundType } from "@/lib/types";
import { FundStatusBadge, MetadataStatusBadge, fundTypeLabel } from "./shared";

const LIMIT = 25;

interface FundFormValues {
  name: string;
  fund_type: FundType;
  issuer: string;
  ticker: string;
  share_class: string;
  sec_cik: string;
  aliases: string;
  description: string;
}

const EMPTY_FORM: FundFormValues = {
  name: "",
  fund_type: "non_traded_reit",
  issuer: "",
  ticker: "",
  share_class: "",
  sec_cik: "",
  aliases: "",
  description: "",
};

export function parseAliases(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((a) => a.trim())
    .filter(Boolean);
}

const opt = (s: string) => (s.trim() ? s.trim() : null);

export function validateFund(v: FundFormValues): Record<string, string> {
  const e: Record<string, string> = {};
  if (!v.name.trim()) e.name = "Enter the fund name.";
  else if (v.name.trim().length > 200) e.name = "Use at most 200 characters.";
  if (v.sec_cik.trim() && !/^\d{1,10}$/.test(v.sec_cik.trim())) e.sec_cik = "SEC CIK is up to 10 digits.";
  if (v.ticker.trim().length > 20) e.ticker = "Use at most 20 characters.";
  if (v.share_class.trim().length > 80) e.share_class = "Use at most 80 characters.";
  return e;
}

function AddFundDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [v, setV] = useState<FundFormValues>(EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: keyof FundFormValues) => (e: { target: { value: string } }) => setV((p) => ({ ...p, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs = validateFund(v);
    setErrors(errs);
    setFormError(null);
    setDuplicate(null);
    if (Object.keys(errs).length) return;
    const body: FundIn = {
      name: v.name.trim(),
      fund_type: v.fund_type,
      issuer: opt(v.issuer),
      ticker: opt(v.ticker)?.toUpperCase() ?? null,
      share_class: opt(v.share_class),
      sec_cik: opt(v.sec_cik),
      aliases: parseAliases(v.aliases),
      description: opt(v.description),
    };
    setSaving(true);
    try {
      const fund = await endpoints.createFund(body);
      toast.success("Fund added to the library");
      setV(EMPTY_FORM);
      onClose();
      router.push(`/funds/${fund.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.isConflict) {
        setDuplicate(err.message);
      } else {
        if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
        setFormError(err);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Add fund"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="add-fund-form" loading={saving}>
            Add fund
          </Button>
        </>
      }
    >
      <form id="add-fund-form" onSubmit={submit} noValidate className="space-y-3">
        {duplicate && (
          <div role="alert">
            <Notice tone="warning" title="This fund is already in your library">
              {duplicate} Search the library for it and use the existing entry instead of adding a duplicate.
            </Notice>
          </div>
        )}
        {formError ? <ErrorState error={formError} /> : null}
        <TextField label="Name" required value={v.name} onChange={set("name")} error={errors.name} maxLength={200} />
        <SelectField
          label="Fund type"
          required
          value={v.fund_type}
          onChange={set("fund_type")}
          error={errors.fund_type}
          options={FUND_TYPES.map((t) => ({ value: t, label: fundTypeLabel(t) }))}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Issuer / sponsor" value={v.issuer} onChange={set("issuer")} error={errors.issuer} />
          <TextField label="Ticker" value={v.ticker} onChange={set("ticker")} error={errors.ticker} />
          <TextField label="Share class" value={v.share_class} onChange={set("share_class")} error={errors.share_class} />
          <TextField
            label="SEC CIK"
            inputMode="numeric"
            value={v.sec_cik}
            onChange={set("sec_cik")}
            error={errors.sec_cik}
            hint="Digits only."
          />
        </div>
        <TextField label="Aliases" value={v.aliases} onChange={set("aliases")} error={errors.aliases} hint="Other names, separated by commas." />
        <TextAreaField label="Description" value={v.description} onChange={set("description")} error={errors.description} />
      </form>
    </Dialog>
  );
}

export function FundLibrary() {
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [fundType, setFundType] = useState<FundType | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [offset, setOffset] = useState(0);
  const [adding, setAdding] = useState(false);

  const list = useApiQuery(
    () => endpoints.searchFunds({ q, fund_type: fundType, include_archived: includeArchived, limit: LIMIT, offset }),
    [q, fundType, includeArchived, offset],
  );

  const search = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setQ(draft.trim());
  };

  const filtered = Boolean(q || fundType || includeArchived);

  return (
    <div>
      <PageHeader
        title="Fund Library"
        description="Shared offering documents and their terms for the funds your firm's households hold. Library terms need reviewer approval before any simulation uses them."
        actions={<Button onClick={() => setAdding(true)}>Add fund</Button>}
      />
      <form onSubmit={search} role="search" className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1">
          <TextField label="Search funds" placeholder="Name, issuer, ticker or alias" value={draft} onChange={(e) => setDraft(e.target.value)} />
        </div>
        <div className="w-48">
          <SelectField
            label="Fund type"
            value={fundType}
            onChange={(e) => {
              setOffset(0);
              setFundType(e.target.value as FundType | "");
            }}
            options={[{ value: "", label: "All types" }, ...FUND_TYPES.map((t) => ({ value: t, label: fundTypeLabel(t) }))]}
          />
        </div>
        <div className="pb-2">
          <CheckboxField
            label="Include archived"
            checked={includeArchived}
            onChange={(c) => {
              setOffset(0);
              setIncludeArchived(c);
            }}
          />
        </div>
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>

      {list.loading && !list.data ? (
        <LoadingBlock rows={4} />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : !list.data || list.data.items.length === 0 ? (
        <EmptyState
          title={filtered ? "No funds match your search" : "The Fund Library is empty"}
          action={<Button onClick={() => setAdding(true)}>Add fund</Button>}
        >
          {filtered
            ? "Try a different name, issuer or ticker, or clear the filters. If the fund is genuinely missing, add it."
            : "Add the non-traded REITs, interval funds and private funds your households hold, then upload their offering documents."}
        </EmptyState>
      ) : (
        <>
          <TableWrap label="Funds">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>Name</th>
                  <th className={th}>Type</th>
                  <th className={th}>Issuer</th>
                  <th className={th}>Ticker</th>
                  <th className={th}>Share class</th>
                  <th className={thNum}>Documents</th>
                  <th className={thNum}>Approved terms</th>
                  <th className={thNum}>Pending terms</th>
                  <th className={th}>Metadata</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {list.data.items.map((f) => (
                  <tr key={f.id}>
                    <td className={td}>
                      <Link href={`/funds/${f.id}`} className="font-medium text-accent-ink underline-offset-2 hover:underline">
                        {f.name}
                      </Link>{" "}
                      <FundStatusBadge status={f.status} />
                    </td>
                    <td className={td}>{fundTypeLabel(f.fund_type)}</td>
                    <td className={td}>{f.issuer ?? EMPTY}</td>
                    <td className={td}>{f.ticker ?? EMPTY}</td>
                    <td className={td}>{f.share_class ?? EMPTY}</td>
                    <td className={tdNum}>{f.document_count ?? EMPTY}</td>
                    <td className={tdNum}>{f.approved_term_count ?? EMPTY}</td>
                    <td className={tdNum}>{f.pending_term_count ?? EMPTY}</td>
                    <td className={td}>
                      <MetadataStatusBadge status={f.metadata_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <Pagination total={list.data.total} limit={list.data.limit || LIMIT} offset={list.data.offset} onChange={setOffset} />
        </>
      )}
      <AddFundDialog open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}
