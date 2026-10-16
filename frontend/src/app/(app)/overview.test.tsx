import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";
import { deriveActions } from "@/lib/overview";
import type { DocumentOut, HouseholdOut, ReviewQueueOut, ScenarioListItem } from "@/lib/types";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/" }));

import OverviewPage from "./page";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const household = (o: Partial<HouseholdOut> = {}): HouseholdOut => ({
  id: "h1",
  name: "Rivera household",
  reporting_currency: "USD",
  start_calendar_month: 1,
  notes: null,
  is_demo: false,
  role: "owner",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  ...o,
});

const doc = (o: Partial<DocumentOut> = {}): DocumentOut => ({
  id: "d1",
  household_id: "h1",
  category: "sbl_agreement",
  original_filename: "SBL_Agreement.pdf",
  content_type: "application/pdf",
  size_bytes: 1000,
  sha256: null,
  page_count: 4,
  pages_without_text: 0,
  ocr_pages: 0,
  status: "extracted",
  is_demo_fixture: false,
  error_code: null,
  error_message: null,
  created_at: "2026-01-03T00:00:00Z",
  updated_at: "2026-01-03T00:00:00Z",
  ...o,
});

const scenario = (o: Partial<ScenarioListItem> = {}): ScenarioListItem => ({
  id: "s1",
  name: "Base case",
  household_id: "h1",
  household_name: "Rivera household",
  updated_at: "2026-01-04T00:00:00Z",
  latest_run_id: null,
  latest_run_at: null,
  latest_first_shortfall_month: null,
  latest_peak_shortfall: null,
  ...o,
});

const emptyReview: ReviewQueueOut = { items: [], total: 0, household_items: 0, library_items: 0 };

function mockApi(data: {
  households: HouseholdOut[];
  review: ReviewQueueOut;
  scenarios: ScenarioListItem[];
  documents: DocumentOut[];
}) {
  return installFetch((c) => {
    if (c.method !== "GET") return undefined;
    const page = <T,>(items: T[]) => jsonResponse({ items, total: items.length, limit: 100, offset: 0 });
    if (c.url.startsWith(`${API}/households?`) || c.url === `${API}/households`) return page(data.households);
    if (c.url.startsWith(`${API}/me/review-queue`)) return jsonResponse(data.review);
    if (c.url.startsWith(`${API}/me/scenarios`)) return jsonResponse(data.scenarios);
    if (c.url.startsWith(`${API}/me/documents`)) return page(data.documents);
    return undefined;
  });
}

describe("deriveActions", () => {
  it("asks to create a household when there are none", () => {
    const [next] = deriveActions({ households: [], review: emptyReview, scenarios: [], documents: [] });
    expect(next).toMatchObject({ kind: "create_household", href: "/households/new" });
  });

  it("puts failed documents before pending review and shortfalls", () => {
    const actions = deriveActions({
      households: [household()],
      review: { ...emptyReview, total: 2, household_items: 2 },
      scenarios: [scenario({ latest_run_id: "r1", latest_run_at: "2026-01-05T00:00:00Z", latest_first_shortfall_month: 4, latest_peak_shortfall: "900.00" })],
      documents: [doc({ id: "d9", status: "failed", error_message: "PDF has no text layer" })],
    });
    expect(actions.map((a) => a.kind)).toEqual(["failed_documents", "review_terms", "open_shortfall"]);
    expect(actions[0]).toMatchObject({ href: "/households/h1/documents/d9", reason: "Processing failed: PDF has no text layer" });
  });

  it("asks to run a scenario for a household with extracted documents and no run", () => {
    const [next] = deriveActions({
      households: [household()],
      review: emptyReview,
      scenarios: [scenario()],
      documents: [doc()],
    });
    expect(next).toMatchObject({ kind: "run_scenario", href: "/households/h1/scenarios/s1", cta: "Open scenario" });
  });

  it("reports nothing outstanding only when every source is clear", () => {
    const [next] = deriveActions({
      households: [household()],
      review: emptyReview,
      scenarios: [scenario({ latest_run_id: "r1", latest_run_at: "2026-01-05T00:00:00Z" })],
      documents: [doc()],
    });
    expect(next!.kind).toBe("all_current");
  });
});

describe("OverviewPage", () => {
  it("with no households, offers to create one or a demo household", async () => {
    mockApi({ households: [], review: emptyReview, scenarios: [], documents: [] });
    render(<OverviewPage />);
    expect(await screen.findByTestId("next-action-title")).toHaveTextContent("Create a household");
    const panel = screen.getByTestId("next-action-title").closest("section")!;
    expect(within(panel).getByRole("link", { name: "Create household" })).toHaveAttribute("href", "/households/new");
    expect(within(panel).getByRole("button", { name: /Create demo household/ })).toBeInTheDocument();
    expect(screen.getByText("No households yet")).toBeInTheDocument();
  });

  it("with terms awaiting review, sends the advisor to the Review Queue", async () => {
    mockApi({
      households: [household()],
      review: { ...emptyReview, total: 3, household_items: 2, library_items: 1 },
      scenarios: [],
      documents: [doc()],
    });
    render(<OverviewPage />);
    expect(await screen.findByTestId("next-action-title")).toHaveTextContent("Review 3 extracted terms");
    const panel = screen.getByTestId("next-action-title").closest("section")!;
    expect(within(panel).getByRole("link", { name: "Open Review Queue" })).toHaveAttribute("href", "/review");
    expect(panel).toHaveTextContent("2 from household agreements and 1 from the Fund Library");
  });

  it("with a projected shortfall, lists it earliest first and shows only API numbers", async () => {
    mockApi({
      households: [household(), household({ id: "h2", name: "Chen household" })],
      review: emptyReview,
      scenarios: [
        scenario({ id: "s1", latest_run_id: "r1", latest_run_at: "2026-01-05T00:00:00Z", latest_first_shortfall_month: 9, latest_peak_shortfall: "12500.00" }),
        scenario({ id: "s2", name: "Rate shock", household_id: "h2", household_name: "Chen household", latest_run_id: "r2", latest_run_at: "2026-01-06T00:00:00Z", latest_first_shortfall_month: 4, latest_peak_shortfall: "830.50" }),
      ],
      documents: [doc()],
    });
    const { container } = render(<OverviewPage />);
    expect(await screen.findByTestId("next-action-title")).toHaveTextContent(
      "Open the analysis for Chen household: shortfall projected in month 4",
    );
    const table = screen.getByRole("region", { name: "Projected shortfalls table" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Chen household");
    expect(rows[0]).toHaveTextContent("Month 4");
    expect(rows[0]).toHaveTextContent("$830.50");
    expect(rows[1]).toHaveTextContent("$12,500");
    expect(within(rows[0]!).getByRole("link", { name: "Open analysis" })).toHaveAttribute("href", "/households/h2/runs/r2");

    // Every money figure on the page is one of the API's values.
    const money = container.textContent!.match(/[−-]?\$[\d,]+(\.\d+)?/g) ?? [];
    expect(money.length).toBeGreaterThan(0);
    for (const m of money) expect(["$830.50", "$12,500"]).toContain(m);
  });

  it("shows the server error instead of a next action when a source fails", async () => {
    installFetch((c) => {
      if (c.url.startsWith(`${API}/me/review-queue`)) return errorResponse(500, "internal", "Review queue unavailable");
      if (c.url.startsWith(`${API}/me/scenarios`)) return jsonResponse([]);
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    render(<OverviewPage />);
    expect(await screen.findByText("Review queue unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("next-action-title")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
