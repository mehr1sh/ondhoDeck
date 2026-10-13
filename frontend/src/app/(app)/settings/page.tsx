"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  PageHeader,
  Pagination,
  SyntheticBadge,
  TableWrap,
  TextField,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { DocumentStatusBadge } from "@/components/badges";
import { useSession } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { formatBytes, formatDateTime, humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { DocumentOut } from "@/lib/types";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

const CONFIRM_PHRASE = "DELETE MY ACCOUNT";
const DOC_LIMIT = 25;

function ProfileForm() {
  const toast = useToast();
  const me = useApiQuery(() => endpoints.getMe(), []);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (me.data) {
      setName(me.data.display_name ?? "");
      setCurrency(me.data.reporting_currency);
    }
  }, [me.data]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (name.length > 120) v.display_name = "Use at most 120 characters.";
    if (!/^[A-Za-z]{3}$/.test(currency.trim())) v.reporting_currency = "Use a 3-letter ISO 4217 code.";
    setErrors(v);
    setFormError(null);
    if (Object.keys(v).length) return;
    setSaving(true);
    try {
      const updated = await endpoints.updateMe({
        display_name: name.trim() ? name.trim() : null,
        reporting_currency: currency.trim().toUpperCase(),
      });
      me.setData(updated);
      toast.success("Profile saved");
    } catch (err) {
      if (err instanceof ApiError && err.isValidation) setErrors(err.fieldErrors);
      setFormError(err);
    } finally {
      setSaving(false);
    }
  };

  if (me.loading && !me.data) return <LoadingBlock rows={2} />;
  if (me.error || !me.data) return <ErrorState error={me.error} onRetry={() => void me.reload()} />;
  return (
    <form onSubmit={submit} noValidate className="max-w-xl space-y-3">
      {formError ? <ErrorState error={formError} /> : null}
      <p className="text-sm text-slate-700">
        Signed in as <strong className="break-all">{me.data.email ?? "unknown email"}</strong> · member since{" "}
        {formatDateTime(me.data.created_at)}
      </p>
      <TextField label="Display name" value={name} maxLength={120} error={errors.display_name} onChange={(e) => setName(e.target.value)} />
      <TextField
        label="Default reporting currency"
        value={currency}
        maxLength={3}
        required
        error={errors.reporting_currency}
        hint="Used as the default for new households."
        onChange={(e) => setCurrency(e.target.value.toUpperCase())}
      />
      <Button type="submit" loading={saving}>
        Save profile
      </Button>
    </form>
  );
}

function MyDocuments() {
  const toast = useToast();
  const [offset, setOffset] = useState(0);
  const docs = useApiQuery(() => endpoints.myDocuments({ limit: DOC_LIMIT, offset }), [offset]);
  const [target, setTarget] = useState<DocumentOut | null>(null);
  const [deleting, setDeleting] = useState(false);

  const remove = async () => {
    if (!target) return;
    setDeleting(true);
    try {
      await endpoints.deleteDocument(target.id);
      toast.success("Document deleted");
      setTarget(null);
      await docs.reload();
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setDeleting(false);
    }
  };

  if (docs.loading && !docs.data) return <LoadingBlock />;
  if (docs.error || !docs.data) return <ErrorState error={docs.error} onRetry={() => void docs.reload()} />;
  if (docs.data.items.length === 0) return <EmptyState title="You have not uploaded any documents" />;
  return (
    <>
      <TableWrap label="My documents">
        <table className={tableClass}>
          <thead>
            <tr>
              <th className={th}>File</th>
              <th className={th}>Category</th>
              <th className={th}>Status</th>
              <th className={thNum}>Size</th>
              <th className={th}>Uploaded</th>
              <th className={th}>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className={tbodyClass}>
            {docs.data.items.map((d) => (
              <tr key={d.id}>
                <td className={td}>
                  <Link href={`/households/${d.household_id}/documents/${d.id}`} className="break-all underline-offset-2 hover:underline">
                    {d.original_filename}
                  </Link>{" "}
                  {d.is_demo_fixture && <SyntheticBadge />}
                </td>
                <td className={td}>{humanize(d.category)}</td>
                <td className={td}>
                  <DocumentStatusBadge status={d.status} />
                </td>
                <td className={tdNum}>{formatBytes(d.size_bytes)}</td>
                <td className={td}>{formatDateTime(d.created_at)}</td>
                <td className={td}>
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setTarget(d)} aria-label={`Delete ${d.original_filename}`}>
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      <Pagination total={docs.data.total} limit={docs.data.limit || DOC_LIMIT} offset={docs.data.offset} onChange={setOffset} />
      <Dialog
        open={target !== null}
        title="Delete document?"
        onClose={() => setTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={deleting}>
              Delete document
            </Button>
          </>
        }
      >
        <p>
          Delete <strong className="break-all">{target?.original_filename}</strong>? The stored file, its extracted page
          text and all constraints extracted from it are permanently deleted. An audit record of the deletion remains.
        </p>
      </Dialog>
    </>
  );
}

function DeleteAccount() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await endpoints.deleteMe();
      await getSupabaseBrowserClient().auth.signOut();
      router.replace("/login");
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <>
      <p className="text-sm text-slate-700">
        Permanently deletes your SlipSlopes account data, including uploaded files and their extracted text. This cannot be
        undone.
      </p>
      <Button variant="danger" className="mt-3" onClick={() => setOpen(true)}>
        Delete my account
      </Button>
      <Dialog
        open={open}
        title="Delete your account?"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy} disabled={typed !== CONFIRM_PHRASE}>
              Delete account permanently
            </Button>
          </>
        }
      >
        <p>
          This cannot be undone. Type <strong className="font-mono">{CONFIRM_PHRASE}</strong> to confirm.
        </p>
        <TextField label="Confirmation" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        {error ? <ErrorState error={error} /> : null}
      </Dialog>
    </>
  );
}

function HouseholdAuditLinks() {
  const q = useApiQuery(() => endpoints.listHouseholds({ limit: 100 }), []);
  if (q.loading && !q.data) return <LoadingBlock rows={2} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  if (q.data.items.length === 0) return <p className="text-sm text-slate-600">No households.</p>;
  return (
    <ul className="divide-y divide-slate-100 text-sm">
      {q.data.items.map((h) => (
        <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <span>
            {h.name} {h.is_demo && <SyntheticBadge />}
          </span>
          <Link href={`/households/${h.id}/settings`} className="underline">
            Audit trail &amp; household settings
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function SettingsPage() {
  const { signOut } = useSession();
  return (
    <div className="space-y-5">
      <PageHeader title="Settings" actions={<Button variant="secondary" onClick={signOut}>Sign out</Button>} />
      <Card title="Profile">
        <ProfileForm />
      </Card>
      <Card title="My documents">
        <p className="mb-3 text-sm text-slate-600">All documents across your households.</p>
        <MyDocuments />
      </Card>
      <Card title="Households and audit trails">
        <HouseholdAuditLinks />
      </Card>
      <Card title="Delete account">
        <DeleteAccount />
      </Card>
    </div>
  );
}
