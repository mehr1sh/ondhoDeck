import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { AssetsSection } from "./sections";

const asset = {
  id: "a1",
  household_id: "h1",
  kind: "brokerage",
  name: "Brokerage account",
  amount: "250000.00",
  currency: "USD",
  as_of: null,
  pledged_to_sbl: true,
  unfunded_commitment: null,
  liquidity_notes: null,
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

describe("Asset form", () => {
  it("validates input before submitting", async () => {
    const { calls } = installFetch(() => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }));
    const user = userEvent.setup();
    render(<AssetsSection householdId="h1" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Amount/), "-5");
    await user.clear(within(dialog).getByLabelText(/Currency/));
    await user.type(within(dialog).getByLabelText(/Currency/), "US");
    await user.click(within(dialog).getByRole("button", { name: "Add asset" }));
    expect(await within(dialog).findByText("Name is required.")).toBeInTheDocument();
    expect(within(dialog).getByText("Amount cannot be negative.")).toBeInTheDocument();
    expect(within(dialog).getByText("Use a 3-letter ISO 4217 code.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("POSTs to the household assets endpoint and refreshes the list", async () => {
    let created = false;
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url.startsWith(`${API}/households/h1/assets`)) {
        return jsonResponse({ items: created ? [asset] : [], total: created ? 1 : 0, limit: 100, offset: 0 });
      }
      if (c.method === "POST" && c.url === `${API}/households/h1/assets`) {
        created = true;
        return jsonResponse(asset, 201);
      }
      return undefined;
    });
    const user = userEvent.setup();
    render(<AssetsSection householdId="h1" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText(/Kind/), "brokerage");
    await user.type(within(dialog).getByLabelText(/Name/), "Brokerage account");
    await user.type(within(dialog).getByLabelText(/Amount/), "250,000.00");
    await user.click(within(dialog).getByLabelText(/Pledged/));
    await user.click(within(dialog).getByRole("button", { name: "Add asset" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe(`${API}/households/h1/assets`);
    expect(post.body).toMatchObject({
      kind: "brokerage",
      name: "Brokerage account",
      amount: "250000.00",
      currency: "USD",
      pledged_to_sbl: true,
      unfunded_commitment: null,
    });
    expect(await screen.findByText("$250,000")).toBeInTheDocument();
  });

  it("shows server-side 422 field errors", async () => {
    installFetch((c) => {
      if (c.method === "GET") return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
      return errorResponse(422, "validation_error", "Invalid input", "req-9", [
        { loc: ["body", "name"], msg: "Name already used" },
      ]);
    });
    const user = userEvent.setup();
    render(<AssetsSection householdId="h1" canEdit />);
    await user.click(await screen.findByRole("button", { name: "Add asset" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Name/), "Dup");
    await user.type(within(dialog).getByLabelText(/Amount/), "10");
    await user.click(within(dialog).getByRole("button", { name: "Add asset" }));
    expect(await within(dialog).findByText("Name already used")).toBeInTheDocument();
    expect(within(dialog).getByText(/req-9/)).toBeInTheDocument();
  });
});
