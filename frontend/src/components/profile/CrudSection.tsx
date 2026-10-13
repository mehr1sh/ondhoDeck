"use client";

import { useState, type ReactNode } from "react";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  TableWrap,
  cx,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { useToast } from "@/components/Toast";
import { describeError, useApiQuery } from "@/lib/hooks";
import { RecordForm, type FieldDef } from "./RecordForm";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
}

export interface CrudSectionProps<T extends { id: string }> {
  title: string;
  singular: string;
  description?: ReactNode;
  fields: FieldDef[];
  columns: Column<T>[];
  canEdit: boolean;
  load: () => Promise<T[]>;
  create: (body: Record<string, unknown>) => Promise<T>;
  update: (id: string, body: Record<string, unknown>) => Promise<T>;
  remove: (id: string) => Promise<unknown>;
  emptyText?: string;
  rowLabel: (row: T) => string;
}

export function CrudSection<T extends { id: string }>(props: CrudSectionProps<T>) {
  const { title, singular, fields, columns, canEdit, load, create, update, remove, rowLabel } = props;
  const toast = useToast();
  const q = useApiQuery(load, []);
  const [editing, setEditing] = useState<T | "new" | null>(null);
  const [deleting, setDeleting] = useState<T | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const doDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await remove(deleting.id);
      toast.success(`${singular} deleted`);
      setDeleting(null);
      await q.reload();
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <Card
      title={title}
      actions={
        canEdit ? (
          <Button size="sm" variant="primary" onClick={() => setEditing("new")}>
            Add {singular.toLowerCase()}
          </Button>
        ) : undefined
      }
    >
      {props.description && <div className="mb-3 text-sm text-slate-600">{props.description}</div>}
      {q.loading && !q.data ? (
        <LoadingBlock rows={2} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.reload()} />
      ) : !q.data || q.data.length === 0 ? (
        <EmptyState title={props.emptyText ?? `No ${title.toLowerCase()} yet`} />
      ) : (
        <TableWrap label={title}>
          <table className={tableClass}>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.header} className={c.numeric ? thNum : th}>
                    {c.header}
                  </th>
                ))}
                {canEdit && (
                  <th className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody className={tbodyClass}>
              {q.data.map((row) => (
                <tr key={row.id}>
                  {columns.map((c) => (
                    <td key={c.header} className={cx(c.numeric ? tdNum : td)}>
                      {c.render(row)}
                    </td>
                  ))}
                  {canEdit && (
                    <td className={cx(td, "whitespace-nowrap text-right")}>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(row)} aria-label={`Edit ${rowLabel(row)}`}>
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setDeleting(row)} aria-label={`Delete ${rowLabel(row)}`}>
                        Delete
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}

      <Dialog
        open={editing !== null}
        title={editing === "new" ? `Add ${singular.toLowerCase()}` : `Edit ${singular.toLowerCase()}`}
        onClose={() => setEditing(null)}
      >
        {editing !== null && (
          <RecordForm
            fields={fields}
            initial={editing === "new" ? null : (editing as unknown as Record<string, unknown>)}
            submitLabel={editing === "new" ? `Add ${singular.toLowerCase()}` : "Save changes"}
            onCancel={() => setEditing(null)}
            onSubmit={async (body) => {
              if (editing === "new") {
                await create(body);
                toast.success(`${singular} added`);
              } else {
                await update(editing.id, body);
                toast.success(`${singular} updated`);
              }
              setEditing(null);
              await q.reload();
            }}
          />
        )}
      </Dialog>

      <Dialog
        open={deleting !== null}
        title={`Delete ${singular.toLowerCase()}?`}
        onClose={() => setDeleting(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={doDelete} loading={deleteBusy}>
              Delete
            </Button>
          </>
        }
      >
        <p>
          Delete <strong>{deleting ? rowLabel(deleting) : ""}</strong>? Existing simulation runs keep their saved inputs; new
          runs will no longer include it.
        </p>
      </Dialog>
    </Card>
  );
}
