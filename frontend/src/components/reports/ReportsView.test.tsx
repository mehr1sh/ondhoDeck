import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { ReportsView } from "./ReportsView";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const exp = (o: Record<string, unknown>) => ({
  id: "e1",
  household_id: "h1",
  household_name: "Rivera household",
  run_id: "r1",
  blind_spot_report_id: null,
  kind: "report_pdf",
  status: "ready",
  filename: "rivera-report.pdf",
  size_bytes: 2048,
  error_message: null,
  created_at: "2026-03-01T10:00:00Z",
  completed_at: "2026-03-01T10:00:05Z",
  ...o,
});

const spot = {
  id: "b1",
  household_id: "h2",
  scenario_id: "s7",
  engine_version: "1.0",
  as_of_date: "2026-03-01",
  risk_count: 5,
  blind_spot_count: 2,
  created_at: "2026-03-02T10:00:00Z",
  household_name: "Chen household",
  scenario_name: "Rate shock",
};

describe("ReportsView", () => {
  it("lists exports with human labels, status and download, and blind-spot checks with scenario links", async () => {
    const opened = vi.fn();
    vi.stubGlobal("open", opened);
    const { calls } = installFetch((c) => {
      if (c.url.startsWith(`${API}/me/reports`)) {
        return jsonResponse({
          exports: [
            exp({}),
            exp({ id: "e2", kind: "blind_spot_pdf", run_id: null, blind_spot_report_id: "b0", household_id: "h2", household_name: "Chen household", status: "failed", error_message: "Renderer crashed", filename: null }),
          ],
          blind_spot_reports: [spot],
        });
      }
      if (c.url === `${API}/exports/e1/download`) return jsonResponse({ url: "https://files.test/report.pdf", expires_in: 60 });
      return undefined;
    });
    const user = userEvent.setup();
    render(<ReportsView />);

    const table = await screen.findByRole("region", { name: "Reports and exports table" });
    const rows = within(table).getAllByRole("row").slice(1);
    const pdf = rows.find((r) => r.textContent?.includes("Liquidity report (PDF)"))!;
    expect(pdf).toHaveTextContent("Rivera household");
    expect(pdf).toHaveTextContent("Ready");
    expect(within(pdf).getByRole("link", { name: "Analysis" })).toHaveAttribute("href", "/households/h1/runs/r1");
    const failed = rows.find((r) => r.textContent?.includes("Blind-spot report (PDF)"))!;
    expect(failed).toHaveTextContent("Failed");
    expect(failed).toHaveTextContent("Renderer crashed");
    expect(within(failed).queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();

    await user.click(within(pdf).getByRole("button", { name: /Download Liquidity report/ }));
    expect(calls.some((c) => c.url === `${API}/exports/e1/download`)).toBe(true);
    expect(opened).toHaveBeenCalledWith("https://files.test/report.pdf", "_blank", "noopener,noreferrer");

    const spots = screen.getByRole("region", { name: "Blind-spot checks table" });
    expect(within(spots).getByRole("link", { name: "Rate shock" })).toHaveAttribute("href", "/households/h2/scenarios/s7");
    expect(within(spots).getByRole("link", { name: "Create PDF" })).toHaveAttribute(
      "href",
      "/households/h2/exports?blind_spot_report_id=b1",
    );

    await user.selectOptions(screen.getByLabelText("Type"), "blind_spot_pdf");
    expect(within(table).queryByText("Liquidity report (PDF)")).not.toBeInTheDocument();
  });

  it("shows an empty state with a real action when there are no reports", async () => {
    installFetch((c) => (c.url.startsWith(`${API}/me/reports`) ? jsonResponse({ exports: [], blind_spot_reports: [] }) : undefined));
    render(<ReportsView />);
    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
    const empty = screen.getByText("No reports yet").parentElement!;
    expect(within(empty).getByRole("link", { name: "Open liquidity scenarios" })).toHaveAttribute("href", "/scenarios");
  });
});
