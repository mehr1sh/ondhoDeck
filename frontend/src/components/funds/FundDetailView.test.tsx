import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock, type RecordedCall } from "@/test/utils";
import { fundDetail, term } from "@/test/fixtures";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/funds/f1" }));

import { FundDetailView } from "./FundDetailView";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const older = term({ id: "t1", revision: 2, effective_from: "2025-01-01", pdf_page: 12 });
const newer = term({ id: "t2", revision: 3, effective_from: "2026-09-01", pdf_page: 20, value: "2.0", document_name: "Supplement_2026.pdf" });
const pending = term({ id: "t3", revision: 1, review_status: "needs_review", pdf_page: 30, constraint_type: "settlement_timing" });

function routes(role: string, extra?: (c: RecordedCall) => Response | undefined) {
  return installFetch((c) => {
    const r = extra?.(c);
    if (r) return r;
    if (c.method === "GET" && c.url === `${API}/funds/f1`) return jsonResponse(fundDetail(role));
    if (c.method === "GET" && c.url.startsWith(`${API}/funds/f1/terms`)) {
      return jsonResponse({ as_of: "2026-10-16", terms: [older, newer, pending], applicable_ids: ["t2"] });
    }
    if (c.method === "GET" && c.url.startsWith(`${API}/funds/f1/audit-events`)) {
      return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
    }
    if (c.method === "GET" && c.url === `${API}/documents/d1/pages/12`) {
      return jsonResponse({ document_id: "d1", pdf_page: 12, printed_page: "10", section: null, ocr: false, text: "Repurchases are limited to 5% of the aggregate NAV per quarter in total." });
    }
    return undefined;
  });
}

describe("FundDetailView", () => {
  it("shows terms read-only for advisors", async () => {
    routes("advisor");
    render(<FundDetailView fundId="f1" />);
    const table = await screen.findByRole("region", { name: "Fund terms" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /^Reject/ })).not.toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /^Supersede/ })).not.toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /^Edit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit details" })).not.toBeInTheDocument();
    expect(screen.getByText(/reviewers and admins approve, edit and supersede them/)).toBeInTheDocument();
    expect(screen.getByText(/affect simulations only after a reviewer approves them/)).toBeInTheDocument();
    expect(within(table).getByText("In force")).toBeInTheDocument();
  });

  it("shows reviewer actions and the evidence viewer for reviewers", async () => {
    routes("reviewer");
    const user = userEvent.setup();
    render(<FundDetailView fundId="f1" />);
    const table = await screen.findByRole("region", { name: "Fund terms" });
    expect(within(table).getByRole("button", { name: "Approve Settlement timing, page 30" })).toBeInTheDocument();
    expect(within(table).getAllByRole("button", { name: /^Reject/ }).length).toBeGreaterThan(0);
    expect(within(table).getByRole("button", { name: /^Supersede an older term with Redemption limit, page 20/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit details" })).toBeInTheDocument();

    await user.click(within(table).getByRole("button", { name: "Evidence for Redemption limit, page 12" }));
    const mark = await screen.findByText("limited to 5% of the aggregate NAV per quarter", { selector: "mark" });
    expect(mark).toBeInTheDocument();
  });

  it("supersede sends both revisions, the older term id and the effective date", async () => {
    const { calls } = routes("reviewer", (c) =>
      c.method === "POST" && c.url === `${API}/constraints/t2/supersede` ? jsonResponse([newer, older]) : undefined,
    );
    const user = userEvent.setup();
    render(<FundDetailView fundId="f1" />);
    const table = await screen.findByRole("region", { name: "Fund terms" });
    await user.click(within(table).getByRole("button", { name: "Supersede an older term with Redemption limit, page 20" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Older term it replaces")).toHaveValue("t1");
    await user.type(within(dialog).getByLabelText(/Note/), "2026 supplement");
    await user.click(within(dialog).getByRole("button", { name: "Record supersession" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({
      expected_revision: 3,
      superseded_id: "t1",
      superseded_expected_revision: 2,
      effective_date: "2026-09-01",
      note: "2026 supplement",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
