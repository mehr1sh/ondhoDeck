import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth: {} }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/" }));

import { SidebarNav } from "./AppShell";

describe("SidebarNav", () => {
  it("renders the eight primary sections in order", () => {
    render(<SidebarNav pathname="/funds/abc" reviewCount={null} />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Overview",
      "Households",
      "Fund Library",
      "Documents",
      "Review Queue",
      "Liquidity Scenarios",
      "Reports",
      "Settings",
    ]);
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/",
      "/households",
      "/funds",
      "/documents",
      "/review",
      "/scenarios",
      "/reports",
      "/settings",
    ]);
    expect(within(nav).getByRole("link", { name: "Fund Library" })).toHaveAttribute("aria-current", "page");
    expect(links.filter((l) => l.getAttribute("aria-current") === "page")).toHaveLength(1);
  });

  it.each([
    ["/", "Overview"],
    ["/households/h1/runs/r1", "Households"],
    ["/reports", "Reports"],
    ["/scenarios", "Liquidity Scenarios"],
    ["/settings/ai-providers", "Settings"],
  ])("marks %s as %s", (path, label) => {
    render(<SidebarNav pathname={path} reviewCount={null} />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const active = within(nav)
      .getAllByRole("link")
      .filter((l) => l.getAttribute("aria-current") === "page");
    expect(active.map((l) => l.textContent)).toEqual([label]);
  });

  it("shows the review queue count", () => {
    render(<SidebarNav pathname="/" reviewCount={4} />);
    expect(screen.getByLabelText("4 items awaiting review")).toHaveTextContent("4");
  });
});
