"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Notice,
  SyntheticBadge,
  TableWrap,
  tableClass,
  tbodyClass,
  td,
  tdNum,
  th,
  thNum,
} from "@/components/ui";
import { DocumentStatusBadge, JobStatusBadge } from "@/components/badges";
import { JobProgress } from "@/components/documents/DocumentUploader";
import { useHousehold } from "@/components/household/HouseholdContext";
import { useToast } from "@/components/Toast";
import { itemsOf, resolveApiUrl } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { extractionMethodLabel } from "@/lib/extraction";
import { EMPTY, formatBytes, formatDateTime, humanize } from "@/lib/format";
import { describeError, useApiQuery, usePolling } from "@/lib/hooks";
import { ACTIVE_DOC_STATUSES, phaseForDocument, POLL_INTERVAL_MS } from "@/lib/upload";

export default function DocumentDetailPage() {
  const { docId } = useParams<{ docId: string }>();
  const { household, canEdit } = useHousehold();
  const router = useRouter();
  const toast = useToast();
  const doc = useApiQuery(() => endpoints.getDocument(docId), [docId]);
  const jobs = useApiQuery(async () => itemsOf(await endpoints.documentJobs(docId)), [docId]);
  const [busy, setBusy] = useState<"retry" | "download" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const active = Boolean(doc.data && ACTIVE_DOC_STATUSES.has(doc.data.status));
  usePolling(
    async () => {
      await doc.reload();
      await jobs.reload();
    },
    POLL_INTERVAL_MS,
    active,
  );

  const fail = (e: unknown) => {
    const d = describeError(e);
    toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
  };

  const retry = async () => {
    setBusy("retry");
    try {
      await endpoints.retryDocument(docId);
      toast.success("Processing restarted");
      await Promise.all([doc.reload(), jobs.reload()]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const download = async () => {
    setBusy("download");
    try {
      const signed = await endpoints.downloadDocument(docId);
      window.open(resolveApiUrl(signed.url), "_blank", "noopener,noreferrer");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    try {
      await endpoints.deleteDocument(docId);
      toast.success("Document deleted");
      router.replace(`/households/${household.id}/documents`);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  };

  if (doc.loading && !doc.data) return <LoadingBlock rows={5} />;
  if (doc.error || !doc.data) return <ErrorState error={doc.error} onRetry={() => void doc.reload()} />;
  const d = doc.data;
  const failed = d.status === "failed";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/households/${household.id}/documents`} className="text-xs text-slate-600 hover:underline">
            ← Documents
          </Link>
          <h2 className="mt-1 flex flex-wrap items-center gap-2 break-all font-display text-[1.35rem] leading-snug text-ink">
            {d.original_filename} <DocumentStatusBadge status={d.status} /> {d.is_demo_fixture && <SyntheticBadge />}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={download} loading={busy === "download"} disabled={d.status === "pending_upload"}>
            Download
          </Button>
          {d.status === "extracted" && (
            <Link
              href={`/households/${household.id}/constraints?document_id=${d.id}`}
              className="inline-flex items-center rounded-md border border-slate-800 bg-slate-800 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
            >
              View constraints ({d.constraint_count ?? 0})
            </Link>
          )}
          {canEdit && (
            <Button variant="danger" onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {active && (
        <Card title="Processing">
          <JobProgress state={{ phase: phaseForDocument(d), document: d, job: d.latest_job }} />
        </Card>
      )}

      {failed && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <p className="font-semibold">Processing failed</p>
          <p className="mt-1">{d.error_message ?? d.latest_job?.error_message ?? "No error message was recorded."}</p>
          {(d.error_code ?? d.latest_job?.error_code) && (
            <p className="mt-1 text-xs">
              Code: <code className="font-mono">{d.error_code ?? d.latest_job?.error_code}</code>
            </p>
          )}
          {canEdit && (
            <Button variant="secondary" size="sm" className="mt-2" onClick={retry} loading={busy === "retry"}>
              Retry
            </Button>
          )}
        </div>
      )}

      <Card title="Details">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["Category", humanize(d.category)],
            ["Size", formatBytes(d.size_bytes)],
            ["Pages", d.page_count ?? EMPTY],
            ["Pages without text", d.pages_without_text ?? EMPTY],
            ["OCR pages", d.ocr_pages ?? EMPTY],
            ["Constraints", d.constraint_count ?? 0],
            ["Extraction method", d.latest_job ? (extractionMethodLabel(d.latest_job) ?? EMPTY) : EMPTY],
            ["Uploaded", formatDateTime(d.created_at)],
            ["Updated", formatDateTime(d.updated_at)],
            ["SHA-256", <code key="sha" className="break-all font-mono text-xs">{d.sha256 ?? EMPTY}</code>],
          ].map(([k, v]) => (
            <div key={String(k)}>
              <dt className="text-slate-600">{k}</dt>
              <dd className="tabular-nums text-slate-900">{v}</dd>
            </div>
          ))}
        </dl>
        {d.is_demo_fixture && (
          <div className="mt-3">
            <Notice tone="warning">This is a synthetic sample contract created for the demo. It is not a real agreement.</Notice>
          </div>
        )}
      </Card>

      <Card title="Processing attempts">
        {jobs.loading && !jobs.data ? (
          <LoadingBlock rows={2} />
        ) : jobs.error ? (
          <ErrorState error={jobs.error} onRetry={() => void jobs.reload()} />
        ) : !jobs.data || jobs.data.length === 0 ? (
          <EmptyState title="No processing attempts yet" />
        ) : (
          <TableWrap label="Processing attempts">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={thNum}>Attempt</th>
                  <th className={th}>Status</th>
                  <th className={th}>Stage</th>
                  <th className={thNum}>Progress</th>
                  <th className={th}>Extraction method</th>
                  <th className={th}>Started</th>
                  <th className={th}>Finished</th>
                  <th className={th}>Error</th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {jobs.data.map((j) => (
                  <tr key={j.id}>
                    <td className={tdNum}>
                      {j.attempt}/{j.max_attempts}
                    </td>
                    <td className={td}>
                      <JobStatusBadge status={j.status} />
                    </td>
                    <td className={td}>{j.stage ? humanize(j.stage) : EMPTY}</td>
                    <td className={tdNum}>{j.progress}%</td>
                    <td className={td}>{extractionMethodLabel(j) ?? EMPTY}</td>
                    <td className={td}>{formatDateTime(j.started_at)}</td>
                    <td className={td}>{formatDateTime(j.finished_at)}</td>
                    <td className={td}>{j.error_message ?? EMPTY}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <Dialog
        open={confirmDelete}
        title="Delete this document?"
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy === "delete"}>
              Delete document
            </Button>
          </>
        }
      >
        <p>Deleting a document permanently removes:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>the stored PDF file,</li>
          <li>the extracted page text, and</li>
          <li>all constraints extracted from it (including your review edits).</li>
        </ul>
        <p>
          An audit record of the deletion remains. This cannot be undone.
        </p>
      </Dialog>
    </div>
  );
}
