"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  Pagination,
  TableWrap,
  TextField,
  tableClass,
  tbodyClass,
  td,
  th,
} from "@/components/ui";
import { HouseholdForm } from "@/components/household/HouseholdForm";
import { useHousehold } from "@/components/household/HouseholdContext";
import { useToast } from "@/components/Toast";
import { endpoints } from "@/lib/endpoints";
import { formatDateTime, humanize } from "@/lib/format";
import { describeError, useApiQuery } from "@/lib/hooks";

const AUDIT_LIMIT = 25;

export default function HouseholdSettingsPage() {
  const { household, canEdit, isOwner, reload } = useHousehold();
  const router = useRouter();
  const toast = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);
  const [auditOffset, setAuditOffset] = useState(0);
  const audit = useApiQuery(
    () => endpoints.auditEvents(household.id, { limit: AUDIT_LIMIT, offset: auditOffset }),
    [household.id, auditOffset],
  );

  const doDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await endpoints.deleteHousehold(household.id);
      toast.success("Household deleted");
      router.replace("/households");
    } catch (e) {
      setDeleteError(e);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card title="Household details">
        {!canEdit && <Notice>You have view-only access to this household.</Notice>}
        <HouseholdForm
          initial={household}
          submitLabel="Save changes"
          disabled={!canEdit}
          onSubmit={async (body) => {
            await endpoints.updateHousehold(household.id, body);
            await reload();
            toast.success("Household updated");
          }}
        />
      </Card>

      <Card title="Audit trail">
        {audit.loading && !audit.data ? (
          <LoadingBlock />
        ) : audit.error ? (
          <ErrorState error={audit.error} onRetry={() => void audit.reload()} />
        ) : !audit.data || audit.data.items.length === 0 ? (
          <EmptyState title="No audit events yet" />
        ) : (
          <>
            <TableWrap label="Audit events">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th className={th}>When</th>
                    <th className={th}>Action</th>
                    <th className={th}>Entity</th>
                    <th className={th}>Actor</th>
                    <th className={th}>Details</th>
                  </tr>
                </thead>
                <tbody className={tbodyClass}>
                  {audit.data.items.map((a) => (
                    <tr key={a.id}>
                      <td className={td}>{formatDateTime(a.created_at)}</td>
                      <td className={td}>{humanize(a.action)}</td>
                      <td className={td}>
                        {humanize(a.entity_type)}
                        {a.entity_id && <span className="block font-mono text-xs text-slate-500">{a.entity_id}</span>}
                      </td>
                      <td className={td}>
                        <span className="font-mono text-xs">{a.actor_id ?? "system"}</span>
                      </td>
                      <td className={td}>
                        <code className="block max-w-md whitespace-pre-wrap break-all text-xs text-slate-700">
                          {Object.keys(a.details).length ? JSON.stringify(a.details) : "—"}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <Pagination total={audit.data.total} limit={audit.data.limit || AUDIT_LIMIT} offset={audit.data.offset} onChange={setAuditOffset} />
          </>
        )}
      </Card>

      <Card title="Danger zone">
        {isOwner ? (
          <div className="space-y-2 text-sm text-slate-700">
            <p>
              Deleting this household permanently removes its financial records, scenarios, runs, uploaded contract files,
              extracted page text and constraints. An audit record of the deletion is retained.
            </p>
            <Button variant="danger" onClick={() => setConfirmOpen(true)}>
              Delete household
            </Button>
          </div>
        ) : (
          <p className="text-sm text-slate-600">Only the household owner can delete it.</p>
        )}
      </Card>

      <Dialog
        open={confirmOpen}
        title="Delete household?"
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={doDelete} loading={deleting} disabled={typed !== household.name}>
              Delete permanently
            </Button>
          </>
        }
      >
        <p>
          This cannot be undone. Type the household name <strong>{household.name}</strong> to confirm.
        </p>
        <TextField label="Household name" value={typed} onChange={(e) => setTyped(e.target.value)} />
        {deleteError ? <p role="alert" className="text-red-800">{describeError(deleteError).message}</p> : null}
      </Dialog>
    </div>
  );
}
