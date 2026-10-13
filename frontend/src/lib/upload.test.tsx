import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock, type RecordedCall } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { runUpload, validatePdfFile, type UploadState } from "./upload";
import { DocumentUploader } from "@/components/documents/DocumentUploader";

const SHA = "a".repeat(64);
const hash = async () => SHA;

function doc(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: "d1",
    household_id: "h1",
    category: "prospectus",
    original_filename: "terms.pdf",
    content_type: "application/pdf",
    size_bytes: 4,
    sha256: SHA,
    page_count: null,
    pages_without_text: null,
    ocr_pages: null,
    status,
    is_demo_fixture: false,
    error_code: null,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    latest_job: null,
    constraint_count: 0,
    ...extra,
  };
}

function job(status: string, progress: number, stage: string | null) {
  return {
    id: "j1",
    document_id: "d1",
    status,
    attempt: 1,
    max_attempts: 3,
    progress,
    stage,
    extraction_method: null,
    provider: null,
    model: null,
    error_code: null,
    error_message: null,
    stats: {},
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
  };
}

const pdf = () => new File([new Uint8Array([37, 80, 68, 70])], "terms.pdf", { type: "application/pdf" });

/** Routes the upload flow; `statuses` are returned by successive GET /documents/d1 polls. */
function uploadRouter(statuses: Array<ReturnType<typeof doc>>, opts: { duplicate?: boolean } = {}) {
  let poll = 0;
  return (c: RecordedCall) => {
    if (c.method === "POST" && c.url === `${API}/households/h1/documents`) {
      return jsonResponse({
        document: doc(opts.duplicate ? "extracted" : "pending_upload"),
        upload: opts.duplicate ? null : { method: "PUT", url: "/api/v1/documents/d1/content", content_type: "application/pdf", max_bytes: 1000 },
        duplicate: Boolean(opts.duplicate),
      });
    }
    if (c.method === "PUT" && c.url === `${API}/documents/d1/content`) return jsonResponse(doc("uploaded"));
    if (c.method === "POST" && c.url === `${API}/documents/d1/complete`) return jsonResponse(job("queued", 0, null), 202);
    if (c.method === "POST" && c.url === `${API}/documents/d1/retry`) return jsonResponse(job("queued", 0, null), 202);
    if (c.method === "GET" && c.url === `${API}/documents/d1`) {
      const d = statuses[Math.min(poll, statuses.length - 1)]!;
      poll++;
      return jsonResponse(d);
    }
    return undefined;
  };
}

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("validatePdfFile", () => {
  it("rejects non-PDF, empty and oversized files", () => {
    expect(validatePdfFile(new File(["x"], "a.txt", { type: "text/plain" }))).toMatch(/Only PDF/);
    expect(validatePdfFile(new File([], "a.pdf", { type: "application/pdf" }))).toMatch(/empty/);
    expect(validatePdfFile(pdf(), 2)).toMatch(/maximum/);
    expect(validatePdfFile(pdf())).toBeNull();
  });
});

describe("runUpload state machine", () => {
  it("initiates, uploads, completes and polls every 2s until extracted", async () => {
    vi.useFakeTimers();
    const { calls } = installFetch(
      uploadRouter([
        doc("queued", { latest_job: job("queued", 0, null) }),
        doc("processing", { latest_job: job("running", 50, "extracting") }),
        doc("extracted", { constraint_count: 7 }),
      ]),
    );
    const states: UploadState[] = [];
    const done = runUpload("h1", pdf(), "prospectus", (s) => states.push(s), { hash });

    await vi.advanceTimersByTimeAsync(0);
    expect(states.map((s) => s.phase)).toEqual(["hashing", "initiating", "uploading", "completing", "processing"]);
    expect(calls.filter((c) => c.url === `${API}/documents/d1`)).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(2000);
    expect(calls.filter((c) => c.url === `${API}/documents/d1`)).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(states.at(-1)!.job?.stage).toBe("extracting");
    await vi.advanceTimersByTimeAsync(2000);

    const final = await done;
    expect(final.phase).toBe("extracted");
    expect(final.document?.constraint_count).toBe(7);

    const init = calls[0]!;
    expect(init.body).toEqual({ filename: "terms.pdf", category: "prospectus", size_bytes: 4, sha256: SHA });
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.headers["Content-Type"]).toBe("application/pdf");
    expect(put.headers.Authorization).toBe("Bearer test-token");
    expect(calls.find((c) => c.url.endsWith("/complete"))!.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("stops at the existing document when the upload is a duplicate", async () => {
    const { calls } = installFetch(uploadRouter([], { duplicate: true }));
    const final = await runUpload("h1", pdf(), "prospectus", () => {}, { hash });
    expect(final.phase).toBe("duplicate");
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("reports server errors with the request id", async () => {
    installFetch(() =>
      jsonResponse({ error: { code: "unsupported_media_type", message: "Not a PDF", request_id: "req-415" } }, 415),
    );
    const final = await runUpload("h1", pdf(), "prospectus", () => {}, { hash });
    expect(final.phase).toBe("error");
    expect(final.error).toMatchObject({ message: "Not a PDF", requestId: "req-415" });
  });
});

describe("DocumentUploader", () => {
  it("shows progress, then a Retry button when processing fails, and retries", async () => {
    vi.useFakeTimers();
    const failed = doc("failed", { error_message: "Could not parse PDF", latest_job: job("failed", 30, "parsing") });
    const { calls } = installFetch(
      uploadRouter([doc("processing", { latest_job: job("running", 30, "parsing") }), failed, doc("processing"), doc("extracted")]),
    );
    const onChanged = vi.fn();
    render(<DocumentUploader householdId="h1" onChanged={onChanged} deps={{ hash }} />);

    const input = screen.getByLabelText(/PDF file/);
    fireEvent.change(input, { target: { files: [pdf()] } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Upload" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText(/Processing document/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "30");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("Could not parse PDF")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry processing" });

    await act(async () => {
      fireEvent.click(retry);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls.some((c) => c.method === "POST" && c.url === `${API}/documents/d1/retry`)).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(screen.getByText(/Extraction finished/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("validates the file type client-side", async () => {
    installFetch(() => undefined);
    render(<DocumentUploader householdId="h1" deps={{ hash }} />);
    fireEvent.change(screen.getByLabelText(/PDF file/), {
      target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] },
    });
    expect(screen.getByText(/Only PDF files/)).toBeInTheDocument();
  });
});

describe("sha256Hex", () => {
  it("hashes file bytes with Web Crypto", async () => {
    const { sha256Hex } = await import("./upload");
    const hex = await sha256Hex(new File(["abc"], "a.pdf", { type: "application/pdf" }));
    expect(hex).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});
