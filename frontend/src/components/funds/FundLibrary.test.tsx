import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";
import { fund } from "@/test/fixtures";

const { auth, push } = vi.hoisted(() => ({ auth: {} as Record<string, unknown>, push: vi.fn() }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

import { FundLibrary } from "./FundLibrary";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
  push.mockReset();
});

describe("FundLibrary", () => {
  it("searches and renders results", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url.startsWith(`${API}/funds`)) {
        const q = new URL(c.url).searchParams.get("q");
        const items = q === "income" ? [fund()] : [];
        return jsonResponse({ items, total: items.length, limit: 25, offset: 0 });
      }
      return undefined;
    });
    const user = userEvent.setup();
    render(<FundLibrary />);
    expect(await screen.findByText("The Fund Library is empty")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search funds"), "income");
    await user.click(screen.getByRole("button", { name: "Search" }));
    const link = await screen.findByRole("link", { name: "Example Income REIT" });
    expect(link).toHaveAttribute("href", "/funds/f1");
    expect(screen.getByText("Example Sponsor")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("q=income"))).toBe(true);
  });

  it("shows an empty state for a search without matches", async () => {
    installFetch(() => jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));
    const user = userEvent.setup();
    render(<FundLibrary />);
    await screen.findByText("The Fund Library is empty");
    await user.type(screen.getByLabelText("Search funds"), "nothing");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No funds match your search")).toBeInTheDocument();
  });

  it("tells the user to search when a fund already exists (409)", async () => {
    installFetch((c) => {
      if (c.method === "GET") return jsonResponse({ items: [], total: 0, limit: 25, offset: 0 });
      return errorResponse(409, "conflict", "This firm's library already has a fund with that name and share class.");
    });
    const user = userEvent.setup();
    render(<FundLibrary />);
    await screen.findByText("The Fund Library is empty");
    await user.click(screen.getAllByRole("button", { name: "Add fund" })[0]!);
    const dialog = screen.getByRole("dialog");
    await user.type(screen.getByLabelText(/^Name/), "Example Income REIT");
    await user.click(dialog.querySelector("button[type=submit]") as HTMLElement);
    expect(await screen.findByText("This fund is already in your library")).toBeInTheDocument();
    expect(screen.getByText(/Search the library for it/)).toBeInTheDocument();
    await waitFor(() => expect(push).not.toHaveBeenCalled());
  });
});
