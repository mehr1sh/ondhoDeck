/**
 * PDF upload flow:
 *   validate -> hash (SHA-256) -> initiate -> (duplicate? stop) -> PUT bytes -> complete -> poll status
 * Polling continues every `pollIntervalMs` while the document is queued/processing.
 */
import { ApiError } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import type { DocCategory, DocumentOut, JobOut } from "@/lib/types";

/** Mirrors the API default (max_upload_mb=50); the server-provided max_bytes is checked too. */
export const MAX_CLIENT_UPLOAD_BYTES = 50 * 1024 * 1024;
export const POLL_INTERVAL_MS = 2000;

export type UploadPhase =
  | "idle"
  | "hashing"
  | "initiating"
  | "uploading"
  | "completing"
  | "processing"
  | "extracted"
  | "failed"
  | "duplicate"
  | "error";

export interface UploadState {
  phase: UploadPhase;
  document?: DocumentOut;
  job?: JobOut | null;
  /** Client- or server-side error to display. */
  error?: { message: string; requestId?: string | null; code?: string };
}

export const ACTIVE_DOC_STATUSES = new Set(["uploaded", "queued", "processing"]);

export function validatePdfFile(file: File | null | undefined, maxBytes = MAX_CLIENT_UPLOAD_BYTES): string | null {
  if (!file) return "Choose a PDF file to upload.";
  const name = file.name.toLowerCase();
  const typeOk = file.type === "application/pdf" || (file.type === "" && name.endsWith(".pdf"));
  if (!typeOk || !name.endsWith(".pdf")) return "Only PDF files (.pdf) can be uploaded.";
  if (file.size <= 0) return "The selected file is empty.";
  if (file.size > maxBytes) {
    return `The file is ${(file.size / (1024 * 1024)).toFixed(1)} MB; the maximum is ${(maxBytes / (1024 * 1024)).toFixed(0)} MB.`;
  }
  return null;
}

function readBytes(file: Blob): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === "function") return file.arrayBuffer();
  // Older engines: fall back to FileReader.
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("Could not read file"));
    reader.readAsArrayBuffer(file);
  });
}

export async function sha256Hex(file: Blob): Promise<string> {
  const buf = await readBytes(file);
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(buf));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export interface UploadDeps {
  hash?: (file: Blob) => Promise<string>;
  pollIntervalMs?: number;
  sleep?: (ms: number) => Promise<void>;
  signal?: { cancelled: boolean };
  maxBytes?: number;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function toErrorState(e: unknown): UploadState["error"] {
  if (e instanceof ApiError) return { message: e.message, requestId: e.requestId, code: e.code };
  return { message: e instanceof Error ? e.message : "Upload failed." };
}

/** Maps a document's status to an upload phase. */
export function phaseForDocument(doc: DocumentOut): UploadPhase {
  if (doc.status === "extracted") return "extracted";
  if (doc.status === "failed") return "failed";
  return "processing";
}

/** Polls a document until it leaves queued/processing (or the run is cancelled). */
export async function pollDocument(
  docId: string,
  onState: (s: UploadState) => void,
  deps: UploadDeps = {},
): Promise<UploadState> {
  const sleep = deps.sleep ?? defaultSleep;
  const interval = deps.pollIntervalMs ?? POLL_INTERVAL_MS;
  for (;;) {
    if (deps.signal?.cancelled) return { phase: "processing" };
    await sleep(interval);
    if (deps.signal?.cancelled) return { phase: "processing" };
    let doc: DocumentOut;
    try {
      doc = await endpoints.getDocument(docId);
    } catch (e) {
      const state: UploadState = { phase: "error", error: toErrorState(e) };
      onState(state);
      return state;
    }
    const phase = phaseForDocument(doc);
    const state: UploadState = { phase, document: doc, job: doc.latest_job ?? null };
    if (phase === "failed") {
      state.error = {
        message: doc.error_message ?? doc.latest_job?.error_message ?? "Processing failed.",
        code: doc.error_code ?? doc.latest_job?.error_code ?? undefined,
      };
    }
    onState(state);
    if (phase !== "processing") return state;
  }
}

/** Runs the full upload flow, reporting each state transition through `onState`. */
export async function runUpload(
  householdId: string,
  file: File,
  category: DocCategory,
  onState: (s: UploadState) => void,
  deps: UploadDeps = {},
): Promise<UploadState> {
  const fail = (e: unknown, document?: DocumentOut): UploadState => {
    const state: UploadState = { phase: "error", document, error: toErrorState(e) };
    onState(state);
    return state;
  };

  const invalid = validatePdfFile(file, deps.maxBytes);
  if (invalid) return fail(new Error(invalid));

  onState({ phase: "hashing" });
  let digest: string;
  try {
    digest = await (deps.hash ?? sha256Hex)(file);
  } catch {
    return fail(new Error("Could not read the file to compute its checksum."));
  }

  onState({ phase: "initiating" });
  let initiated;
  try {
    initiated = await endpoints.initiateUpload(householdId, {
      filename: file.name,
      category,
      size_bytes: file.size,
      sha256: digest,
    });
  } catch (e) {
    return fail(e);
  }

  if (initiated.duplicate) {
    const state: UploadState = { phase: "duplicate", document: initiated.document };
    onState(state);
    return state;
  }
  if (!initiated.upload) {
    return fail(new Error("The API did not return an upload target."), initiated.document);
  }
  if (file.size > initiated.upload.max_bytes) {
    return fail(
      new Error(`The file exceeds the server limit of ${(initiated.upload.max_bytes / (1024 * 1024)).toFixed(0)} MB.`),
      initiated.document,
    );
  }

  const document = initiated.document;
  onState({ phase: "uploading", document });
  try {
    await endpoints.uploadContent(initiated.upload.url, file, initiated.upload.content_type || "application/pdf");
  } catch (e) {
    return fail(e, document);
  }

  onState({ phase: "completing", document });
  let job: JobOut;
  try {
    job = await endpoints.completeUpload(document.id);
  } catch (e) {
    return fail(e, document);
  }

  onState({ phase: "processing", document, job });
  return pollDocument(document.id, onState, deps);
}

export const PHASE_LABELS: Record<UploadPhase, string> = {
  idle: "Ready",
  hashing: "Computing checksum…",
  initiating: "Registering upload…",
  uploading: "Uploading file…",
  completing: "Queuing for processing…",
  processing: "Processing document…",
  extracted: "Extraction complete",
  failed: "Processing failed",
  duplicate: "Already uploaded",
  error: "Upload failed",
};
