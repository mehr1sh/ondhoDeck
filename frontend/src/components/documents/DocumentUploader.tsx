"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button, Card, Notice, SelectField } from "@/components/ui";
import { DocumentStatusBadge } from "@/components/badges";
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { humanize } from "@/lib/format";
import {
  MAX_CLIENT_UPLOAD_BYTES,
  PHASE_LABELS,
  pollDocument,
  runUpload,
  validatePdfFile,
  type UploadDeps,
  type UploadState,
} from "@/lib/upload";
import { DOC_CATEGORIES, type DocCategory } from "@/lib/types";

const BUSY = new Set(["hashing", "initiating", "uploading", "completing", "processing"]);

export function JobProgress({ state }: { state: UploadState }) {
  const job = state.job ?? state.document?.latest_job ?? null;
  const pct = job ? Math.max(0, Math.min(100, job.progress)) : null;
  return (
    <div className="space-y-1">
      <p className="text-sm text-slate-800">
        {PHASE_LABELS[state.phase]}
        {job?.stage ? <span className="text-slate-600"> · {humanize(job.stage)}</span> : null}
        {job ? <span className="text-slate-600"> · attempt {job.attempt} of {job.max_attempts}</span> : null}
      </p>
      {pct !== null && state.phase === "processing" && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="Processing progress"
          className="h-2 w-full overflow-hidden rounded bg-slate-200"
        >
          <div className="h-full bg-lime-400 transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

export function DocumentUploader({
  householdId,
  onChanged,
  deps,
}: {
  householdId: string;
  onChanged?: () => void;
  /** Test hooks (hash function, polling interval). */
  deps?: UploadDeps;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState<DocCategory>("prospectus");
  const [fileError, setFileError] = useState<string | null>(null);
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [retrying, setRetrying] = useState(false);
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
    if (s.phase === "extracted" || s.phase === "failed" || s.phase === "duplicate" || s.phase === "completing") {
      onChangedRef.current?.();
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const err = validatePdfFile(file);
    setFileError(err);
    if (err || !file) return;
    await runUpload(householdId, file, category, report, { ...deps, signal: signal.current });
  };

  const retry = async () => {
    const doc = state.document;
    if (!doc) return;
    setRetrying(true);
    try {
      const job = await endpoints.retryDocument(doc.id);
      report({ phase: "processing", document: doc, job });
      setRetrying(false);
      await pollDocument(doc.id, report, { ...deps, signal: signal.current });
    } catch (e) {
      setRetrying(false);
      report({
        phase: "failed",
        document: doc,
        error: e instanceof ApiError ? { message: e.message, requestId: e.requestId } : { message: "Retry failed." },
      });
    }
  };

  const busy = BUSY.has(state.phase);
  const doc = state.document;

  return (
    <Card title="Upload a contract (PDF)">
      <form onSubmit={onSubmit} noValidate className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <div className="space-y-1">
          <label htmlFor={inputId} className="block text-sm font-medium text-slate-800">
            PDF file <span aria-hidden="true" className="text-red-700">*</span>
          </label>
          <input
            id={inputId}
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            aria-invalid={fileError ? true : undefined}
            aria-describedby={fileError ? `${inputId}-error` : `${inputId}-hint`}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setFileError(f ? validatePdfFile(f) : null);
              setState({ phase: "idle" });
            }}
            className="block w-full text-sm text-slate-800 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-50"
          />
          {fileError ? (
            <p id={`${inputId}-error`} className="text-xs font-medium text-red-700">
              {fileError}
            </p>
          ) : (
            <p id={`${inputId}-hint`} className="text-xs text-slate-600">
              PDF only, up to {Math.round(MAX_CLIENT_UPLOAD_BYTES / (1024 * 1024))} MB.
            </p>
          )}
        </div>
        <SelectField
          label="Category"
          value={category}
          disabled={busy}
          onChange={(e) => setCategory(e.target.value as DocCategory)}
          options={DOC_CATEGORIES.map((c) => ({ value: c, label: humanize(c) }))}
        />
        <Button type="submit" loading={busy} disabled={!file}>
          Upload
        </Button>
      </form>

      {state.phase !== "idle" && (
        <div className="mt-4 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3" aria-live="polite">
          {doc && (
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-slate-900">{doc.original_filename}</span>
              <DocumentStatusBadge status={doc.status} />
            </p>
          )}
          <JobProgress state={state} />
          {state.phase === "duplicate" && doc && (
            <Notice>
              This file was already uploaded to this household.{" "}
              <Link href={`/households/${householdId}/documents/${doc.id}`} className="underline">
                View the existing document
              </Link>
              .
            </Notice>
          )}
          {state.phase === "extracted" && doc && (
            <Notice tone="success">
              Extraction finished.{" "}
              <Link href={`/households/${householdId}/constraints?document_id=${doc.id}`} className="underline">
                Review extracted constraints
              </Link>
              .
            </Notice>
          )}
          {(state.phase === "failed" || state.phase === "error") && (
            <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
              <p>{state.error?.message ?? "Upload failed."}</p>
              {state.error?.requestId && (
                <p className="mt-1 text-xs">
                  Request ID: <code className="font-mono">{state.error.requestId}</code>
                </p>
              )}
              {state.phase === "failed" && doc && (
                <Button variant="secondary" size="sm" className="mt-2" onClick={retry} loading={retrying}>
                  Retry processing
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
