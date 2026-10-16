import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";
import { term } from "@/test/fixtures";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { ReviewQueue } from "./ReviewQueue";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const householdItem = {
  constraint: term({ id: "hc1", household_id: "h1", fund_id: null, revision: 4, review_status: "needs_review", document_name: "SBL_Agreement.pdf", constraint_type: "maintenance_ltv" }),
  owner_type: "household",
  owner_id: "h1",
  owner_name: "Rivera household",
};
const fundItem = {
  constraint: term({ id: "fc1", revision: 1, review_status: "needs_review" }),
  owner_type: "fund",
  owner_id: "f1",
  owner_name: "Example Income REIT",
};

describe("ReviewQueue", () => {
  it("filters by owner and approves with expected_revision, then refreshes", async () => {
    let approved = false;
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url.startsWith(`${API}/me/review-queue`)) {
        const items = approved ? [fundItem] : [householdItem, fundItem];
        return jsonResponse({ items, total: items.length, household_items: approved ? 0 : 1, library_items: 1 });
      }
      if (c.method === "POST" && c.url === `${API}/constraints/hc1/approve`) {
        approved = true;
        return jsonResponse({ ...householdItem.constraint, revision: 5, review_status: "confirmed", revisions: [] });
      }
      return undefined;
    });
    const user = userEvent.setup();
    render(<ReviewQueue />);
    const table = await screen.findByRole("region", { name: "Terms awaiting review" });
    expect(within(table).getByRole("link", { name: "Maintenance LTV" })).toHaveAttribute("href", "/households/h1/constraints/hc1");
    expect(within(table).getByRole("link", { name: "Redemption limit" })).toHaveAttribute("href", "/funds/f1");

    await user.click(screen.getByRole("tab", { name: /Fund Library/ }));
    expect(within(screen.getByRole("region", { name: "Terms awaiting review" })).queryByText("Rivera household")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^All/ }));

    await user.click(screen.getByRole("button", { name: "Approve Maintenance LTV from Rivera household" }));
    await waitFor(() => expect(screen.queryByText("Rivera household")).not.toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ expected_revision: 4 });
    expect(calls.filter((c) => c.url.startsWith(`${API}/me/review-queue`)).length).toBeGreaterThanOrEqual(2);
  });
});
