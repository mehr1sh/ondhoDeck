"use client";

import { useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Dialog,
  ErrorState,
  LoadingBlock,
  SelectField,
  TableWrap,
  TextField,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { ROLE_DESCRIPTIONS } from "@/components/funds/shared";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDate, humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";
import { FIRM_ROLES, type FirmMemberOut, type FirmOut, type FirmRole } from "@/lib/types";

const roleOptions = FIRM_ROLES.map((r) => ({ value: r, label: humanize(r) }));

function memberError(e: unknown, action: "add" | "change" | "remove"): string {
  if (e instanceof ApiError) {
    if (action === "add" && e.status === 404) return "No account with that email yet. Ask them to sign up first, then add them.";
    if (e.status === 409) return e.message || "A firm needs at least one admin. Promote someone else first.";
  }
  return describeError(e).message;
}

function Members({ firm }: { firm: FirmOut }) {
  const toast = useToast();
  const isAdmin = firm.role === "admin";
  const q = useApiQuery(() => endpoints.firmMembers(firm.id), [firm.id]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<FirmRole>("advisor");
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<FirmMemberOut | null>(null);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setAddError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setAddError("Enter a valid email address.");
      return;
    }
    setAdding(true);
    try {
      const members = await endpoints.addFirmMember(firm.id, { email: email.trim(), role });
      if (Array.isArray(members)) q.setData(members);
      else await q.reload();
      setEmail("");
      toast.success("Member added");
    } catch (err) {
      setAddError(memberError(err, "add"));
    } finally {
      setAdding(false);
    }
  };

  const changeRole = async (m: FirmMemberOut, next: FirmRole) => {
    setBusy(m.user_id);
    try {
      const members = await endpoints.changeFirmMemberRole(firm.id, m.user_id, next);
      if (Array.isArray(members)) q.setData(members);
      else await q.reload();
      toast.success("Role updated");
    } catch (err) {
      toast.error(memberError(err, "change"));
      await q.reload();
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!removing) return;
    setBusy(removing.user_id);
    try {
      await endpoints.removeFirmMember(firm.id, removing.user_id);
      toast.success("Member removed");
      setRemoving(null);
      await q.reload();
    } catch (err) {
      toast.error(memberError(err, "remove"));
    } finally {
      setBusy(null);
    }
  };

  if (q.loading && !q.data) return <LoadingBlock rows={2} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;

  return (
    <div className="space-y-3">
      <TableWrap label={`Members of ${firm.name}`}>
        <table className={tableClass}>
          <thead>
            <tr>
              <th className={th}>Member</th>
              <th className={th}>Role</th>
              <th className={th}>Since</th>
              {isAdmin && (
                <th className={th}>
                  <span className="sr-only">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody className={tbodyClass}>
            {q.data.map((m) => (
              <tr key={m.user_id}>
                <td className={td}>
                  {m.display_name ?? m.email ?? EMPTY}
                  {m.display_name && m.email && <span className="block text-xs text-ink-3">{m.email}</span>}
                </td>
                <td className={td}>
                  {isAdmin ? (
                    <select
                      aria-label={`Role for ${m.email ?? m.display_name ?? "member"}`}
                      value={m.role}
                      disabled={busy === m.user_id}
                      onChange={(e) => void changeRole(m, e.target.value as FirmRole)}
                      className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm"
                    >
                      {roleOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Badge>{humanize(m.role)}</Badge>
                  )}
                </td>
                <td className={td}>{formatDate(m.created_at)}</td>
                {isAdmin && (
                  <td className={td}>
                    <Button size="sm" variant="ghost" className="text-risk" onClick={() => setRemoving(m)}>
                      Remove
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
      {isAdmin && (
        <form onSubmit={add} noValidate className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <TextField label="Add member by email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={addError} />
          </div>
          <div className="w-40">
            <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as FirmRole)} options={roleOptions} />
          </div>
          <Button type="submit" loading={adding}>
            Add member
          </Button>
        </form>
      )}
      <Dialog
        open={removing !== null}
        title="Remove member?"
        onClose={() => setRemoving(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy !== null}>
              Remove
            </Button>
          </>
        }
      >
        <p>
          Remove <strong>{removing?.email ?? removing?.display_name}</strong> from {firm.name}? They lose access to the
          firm&apos;s Fund Library.
        </p>
      </Dialog>
    </div>
  );
}

function RenameFirm({ firm, onRenamed }: { firm: FirmOut; onRenamed: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(firm.name);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Enter a firm name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await endpoints.renameFirm(firm.id, name.trim());
      toast.success("Firm renamed");
      onRenamed();
    } catch (err) {
      setError(describeError(err).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-end gap-3">
      <div className="min-w-64 flex-1">
        <TextField label="Firm name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} error={error} />
      </div>
      <Button type="submit" variant="secondary" loading={saving} disabled={name.trim() === firm.name}>
        Rename
      </Button>
    </form>
  );
}

export function FirmSettings() {
  const firms = useApiQuery(() => endpoints.myFirms(), []);
  if (firms.loading && !firms.data) return <LoadingBlock rows={2} />;
  if (firms.error || !firms.data) return <ErrorState error={firms.error} onRetry={() => void firms.reload()} />;
  return (
    <div className="space-y-5">
      <dl className="grid gap-2 text-sm sm:grid-cols-3">
        {FIRM_ROLES.slice()
          .reverse()
          .map((r) => (
            <div key={r} className="rounded-md border border-line p-3">
              <dt className="font-medium text-ink">{humanize(r)}</dt>
              <dd className="mt-1 text-xs text-ink-3">{ROLE_DESCRIPTIONS[r]}</dd>
            </div>
          ))}
      </dl>
      {firms.data.length === 0 ? (
        <p className="text-sm text-ink-3">You are not a member of any firm.</p>
      ) : (
        firms.data.map((f) => (
          <section key={f.id} className="space-y-3 border-t border-line pt-4">
            <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
              {f.name} <Badge tone="info">Your role: {f.role}</Badge>
            </h3>
            {f.role === "admin" && <RenameFirm firm={f} onRenamed={() => void firms.reload()} />}
            <Members firm={f} />
          </section>
        ))
      )}
    </div>
  );
}
