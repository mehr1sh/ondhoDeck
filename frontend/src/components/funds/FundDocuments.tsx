"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  Button,
  Card,
  Dialog,
  ErrorState,
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
import { DocumentStatusBadge } from "@/components/badges";
import { JobProgress } from "@/components/documents/DocumentUploader";
import { useToast } from "@/components/Toast";
import { resolveApiUrl } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { EMPTY, formatDate, humanize } from "@/lib/format";
import { describeError } from "@/lib/hooks";
import { runUploadWith, validatePdfFile, type UploadDeps, type UploadState } from "@/lib/upload";
import { FUND_DOC_CATEGORIES, type DocumentOut, type FundDocCategory } from "@/lib/types";

const BUSY = new Set(["hashing", "initiating", "uploading", "completing", "processing"]);

function FundDocumentUploader({
  fundId,
  documents,
  onChanged,
  deps,
}: {
  fundId: string;
  documents: DocumentOut[];
  onChanged: () => void;
  deps?: UploadDeps;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState<FundDocCategory>("prospectus");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [supersedes, setSupersedes] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const signal = useRef({ cancelled: false });
  const inputId = useId();
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  useEffect(() => {
    const s = signal.current;
    return () => {
      s.cancelled = true;
    };
  }, []);

  const report = (s: UploadState) => {
    if (signal.current.cancelled) return;
    setState(s);
    if (["extracted", "failed", "duplicate", "completing"].includes(s.phase)) onChangedRef.current();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const err = validatePdfFile(file);
    setFileError(err);
    if (err || !file) return;
    await runUploadWith(
      (meta) =>
        endpoints.initiateFundUpload(fundId, {
          ...meta,
          category,
          effective_date: effectiveDate || null,
          supersedes_document_id: supersedes || null,
        }),
      file,
      report,
      { ...deps, signal: signal.current },
    );
  };

  const busy = BUSY.has(state.phase);
  return (
    <form onSubmit={submit} noValidate className="space-y-3 rounded-md border border-line p-3">
      <p className="text-sm font-medium text-ink">Upload an offering document (PDF)</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1">
          <label htmlFor={inputId} className="block text-sm font-medium text-ink">
            PDF file <span aria-hidden="true" className="text-risk">*</span>
          </label>
          <input
            id={inputId}
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            aria-invalid={fileError ? true : undefined}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setFileError(f ? validatePdfFile(f) : null);
              setState({ phase: "idle" });
            }}
            className="block w-full text-sm text-ink file:mr-3 file:rounded-md file:border file:border-line-strong file:bg-surface file:px-3 file:py-1.5 file:text-sm"
          />
          {fileError && <p className="text-xs font-medium text-risk">{fileError}</p>}
        </div>
        <SelectField
          label="Category"
          value={category}
          disabled={busy}
          onChange={(e) => setCategory(e.target.value as FundDocCategory)}
          options={FUND_DOC_CATEGORIES.map((c) => ({ value: c, label: humanize(c) }))}
        />
        <TextField
          label="Effective date"
          type="date"
          value={effectiveDate}
          disabled={busy}
          onChange={(e) => setEffectiveDate(e.target.value)}
          hint="Date on the cover of the document, if known."
        />
        <SelectField
          label="Supersedes"
          value={supersedes}
          disabled={busy}
          onChange={(e) => setSupersedes(e.target.value)}
          options={[
            { value: "", label: "Nothing" },
            ...documents.map((d) => ({ value: d.id, label: d.original_filename })),
          ]}
        />
      </div>
      <Button type="submit" loading={busy} disabled={!file}>
        Upload
      </Button>
      {state.phase !== "idle" && (
        <div className="space-y-2" aria-live="polite">
          <JobProgress state={state} />
          {state.phase === "duplicate" && (
            <Notice>This file is already in the library{state.document ? ` as ${state.document.original_filename}` : ""}.</Notice>
          )}
          {state.phase === "extracted" && (
            <Notice tone="success">Extraction finished. New terms appear below with status “Needs review”.</Notice>
          )}
          {(state.phase === "failed" || state.phase === "error") && (
            <div role="alert" className="rounded-md border border-risk/30 bg-risk-subtle px-3 py-2 text-sm text-risk">
              {state.error?.message ?? "Upload failed."}
              {state.error?.requestId && <span className="block text-xs">Request ID: {state.error.requestId}</span>}
            </div>
          )}
        </div>
      )}
    </form>
  );
}

function LibraryMetadataDialog({
  doc,
  documents,
  onClose,
  onSaved,
}: {
  doc: DocumentOut;
  documents: DocumentOut[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [effectiveDate, setEffectiveDate] = useState(doc.effective_date ?? "");
  const [supersedes, setSupersedes] = useState(doc.supersedes_document_id ?? "");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await endpoints.updateLibraryDocument(doc.id, {
        effective_date: effectiveDate || null,
        supersedes_document_id: supersedes || null,
      });
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog
      open
      title="Document dates"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={saving}>
            Save
          </Button>
        </>
      }
    >
      <p className="break-all font-medium">{doc.original_filename}</p>
      <TextField label="Effective date" type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
      <SelectField
        label="Supersedes"
        value={supersedes}
        onChange={(e) => setSupersedes(e.target.value)}
        options={[
          { value: "", label: "Nothing" },
          ...documents.filter((d) => d.id !== doc.id).map((d) => ({ value: d.id, label: d.original_filename })),
        ]}
      />
      <p className="text-xs text-ink-3">
        Document links are for reference. Which term applies on a date is set per term, with “Supersede” in the Terms table.
      </p>
      {error ? <ErrorState error={error} /> : null}
    </Dialog>
  );
}

export function FundDocuments({
  fundId,
  documents,
  canReview,
  onChanged,
}: {
  fundId: string;
  documents: DocumentOut[];
  canReview: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<DocumentOut | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const name = (id: string | null | undefined) => documents.find((d) => d.id === id)?.original_filename;

  const download = async (id: string) => {
    setDownloading(id);
    try {
      const signed = await endpoints.downloadDocument(id);
      window.open(resolveApiUrl(signed.url), "_blank", "noopener,noreferrer");
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <Card title="Documents">
      <div className="space-y-4">
        {documents.length === 0 ? (
          <p className="text-sm text-ink-3">No offering documents yet.</p>
        ) : (
          <TableWrap label="Fund documents">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={th}>File</th>
                  <th className={th}>Category</th>
                  <th className={th}>Effective date</th>
                  <th className={th}>Supersedes</th>
                  <th className={th}>Status</th>
                  <th className={thNum}>Pages</th>
                  <th className={thNum}>Terms</th>
                  <th className={th}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className={tbodyClass}>
                {documents.map((d) => (
                  <tr key={d.id}>
                    <td className={td}>
                      <span className="break-all">{d.original_filename}</span>
                    </td>
                    <td className={td}>{humanize(d.category)}</td>
                    <td className={td}>{d.effective_date ? formatDate(d.effective_date) : EMPTY}</td>
                    <td className={td}>{d.supersedes_document_id ? name(d.supersedes_document_id) ?? "Earlier document" : EMPTY}</td>
                    <td className={td}>
                      <DocumentStatusBadge status={d.status} />
                    </td>
                    <td className={tdNum}>{d.page_count ?? EMPTY}</td>
                    <td className={tdNum}>{d.constraint_count ?? EMPTY}</td>
                    <td className={td}>
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => download(d.id)} loading={downloading === d.id}>
                          Download
                        </Button>
                        {canReview && (
                          <Button size="sm" variant="ghost" onClick={() => setEditing(d)} aria-label={`Edit dates for ${d.original_filename}`}>
                            Edit dates
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <FundDocumentUploader fundId={fundId} documents={documents} onChanged={onChanged} />
      </div>
      {editing && (
        <LibraryMetadataDialog
          doc={editing}
          documents={documents}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            toast.success("Document updated");
            onChanged();
          }}
        />
      )}
    </Card>
  );
}

