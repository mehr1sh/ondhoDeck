import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { ConstraintReview } from "./ConstraintReview";

function constraint(revision: number, extra: Record<string, unknown> = {}) {
  return {
    id: "c1",
    household_id: "h1",
    document_id: "d1",
    document_name: "SYNTHETIC_Interval_Fund.pdf",
    revision,
    constraint_type: "repurchase_offer_pct",
    asset_key: "interval_fund",
    description: "Quarterly repurchase offer",
    value: "5.0",
    lower_bound: null,
    upper_bound: null,
    original_value: "5.0",
    unit: "percent_of_shares",
    timing: "quarterly",
    conditions: null,
    pdf_page: 3,
    printed_page: "2",
    document_section: "Repurchases",
    evidence_quote: "will offer to repurchase 5% of outstanding shares",
    quote_verified: true,
    corroborating_pages: [4],
    interpretation: "Up to 5% per quarter",
    confidence: "high",
    source_type: "synthetic_document",
    review_status: "needs_review",
    extraction_method: "rules",
    provider: null,
    model: null,
    is_qualitative: false,
    reviewed_at: null,
    updated_at: "2026-01-01T00:00:00Z",
    revisions: [{ revision: 1, changed_by: null, change: { created: true }, note: null, created_at: "2026-01-01T00:00:00Z" }],
    ...extra,
  };
}

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("ConstraintReview", () => {
  it("approves with expected_revision", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/constraints/c1`) return jsonResponse(constraint(2));
      if (c.method === "POST" && c.url === `${API}/constraints/c1/approve`)
        return jsonResponse(constraint(3, { review_status: "confirmed" }));
      return undefined;
    });
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    expect(await screen.findByText(/will offer to repurchase 5%/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Decision note/), "Checked against page 3");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText("Confirmed")).toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ expected_revision: 2, note: "Checked against page 3" });
    expect(screen.getByText("Revision 3", { selector: "span" })).toBeInTheDocument();
  });

  it("handles a 409 conflict by reloading the latest version", async () => {
    let gets = 0;
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/constraints/c1`) {
        gets++;
        return jsonResponse(gets === 1 ? constraint(2) : constraint(4, { review_status: "edited", value: "4.0" }));
      }
      if (c.method === "POST" && c.url === `${API}/constraints/c1/reject`)
        return errorResponse(409, "conflict", "Revision mismatch", "req-409");
      return undefined;
    });
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    await screen.findByText(/will offer to repurchase 5%/);
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText(/Someone else changed this constraint/)).toBeInTheDocument();
    await waitFor(() => expect(gets).toBe(2));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ expected_revision: 2 });
    expect(await screen.findByText("Revision 4", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Edited")).toBeInTheDocument();
  });

  it("sends only changed fields with expected_revision when editing", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET") return jsonResponse(constraint(2));
      if (c.method === "PATCH") return jsonResponse(constraint(3, { value: "4.5", review_status: "edited" }));
      return undefined;
    });
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    await screen.findByText(/will offer to repurchase 5%/);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const value = screen.getByLabelText(/^Value$/);
    await user.clear(value);
    await user.type(value, "4.5");
    await user.type(screen.getByLabelText(/Review note/), "Corrected");
    await user.click(screen.getByRole("button", { name: "Save edits" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ expected_revision: 2, value: "4.5", note: "Corrected" });
  });

  it("does not offer numeric inputs for qualitative constraints", async () => {
    installFetch(() => jsonResponse(constraint(1, { value: null, original_value: null, is_qualitative: true })));
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    await screen.findByText(/will offer to repurchase 5%/);
    expect(screen.getAllByText("qualitative").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.queryByLabelText(/^Value$/)).not.toBeInTheDocument();
    expect(screen.getByText(/numeric values\s+cannot be added/)).toBeInTheDocument();
  });

  it("shows validation issues and ambiguity, and edits value kind, exceptions and discretion", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET")
        return jsonResponse(
          constraint(2, {
            value_kind: "maximum",
            ambiguous: true,
            exceptions: ["death or disability"],
            discretion: null,
            effective_period: null,
            validation_issues: [
              { code: "value_not_in_quote", severity: "warning", message: "value=5 does not appear in the quoted clause." },
            ],
          }),
        );
      if (c.method === "PATCH") return jsonResponse(constraint(3, { review_status: "edited" }));
      return undefined;
    });
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    expect(await screen.findByText("Automated validation warnings")).toBeInTheDocument();
    expect(screen.getByText(/does not appear in the quoted clause/)).toBeInTheDocument();
    expect(screen.getByText("Ambiguous clause")).toBeInTheDocument();
    expect(screen.getByText(/not a guaranteed payout/)).toBeInTheDocument();
    expect(screen.getByText("death or disability")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.selectOptions(screen.getByLabelText("Value kind"), "range");
    await user.type(screen.getByLabelText("Exceptions"), "\nestate planning");
    await user.type(screen.getByLabelText("Discretion"), "Board may suspend");
    await user.click(screen.getByRole("button", { name: "Save edits" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({
      expected_revision: 2,
      value_kind: "range",
      exceptions: ["death or disability", "estate planning"],
      discretion: "Board may suspend",
    });
  });

  it("highlights the quote in the page text panel", async () => {
    installFetch((c) => {
      if (c.url === `${API}/constraints/c1`) return jsonResponse(constraint(1));
      if (c.url === `${API}/documents/d1/pages/3`)
        return jsonResponse({
          document_id: "d1",
          pdf_page: 3,
          printed_page: "2",
          section: "Repurchases",
          ocr: false,
          text: "The Fund will offer to\nrepurchase 5% of outstanding shares each quarter.",
        });
      return undefined;
    });
    const user = userEvent.setup();
    render(<ConstraintReview constraintId="c1" householdId="h1" canEdit />);
    await user.click(await screen.findByRole("button", { name: "View page 3 text" }));
    const mark = await screen.findByText(/will offer to\s+repurchase 5% of outstanding shares/, { selector: "mark" });
    expect(mark.tagName).toBe("MARK");
  });
});
