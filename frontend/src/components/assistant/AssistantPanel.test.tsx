import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { AssistantPanel, householdIdFromPath } from "./AssistantPanel";

beforeEach(() => {
  Object.assign(auth, makeAuthMock());
});

const providers = (active: boolean) => ({
  storage_available: true,
  storage_message: null,
  providers: [{ provider: "anthropic", label: "Anthropic", default_model: "claude-opus-5-5" }],
  credentials: active
    ? [{ provider: "anthropic", key_hint: "…cdef", model: "claude-opus-5-5", is_active: true, status: "valid",
         last_tested_at: null, last_error_code: null, last_error: null, updated_at: "2026-10-16T10:00:00Z" }]
    : [],
  active_provider: active ? "anthropic" : null,
  server_fallback: { configured: false, provider: null, model: null },
  extraction_order: "",
});

const chat = { id: "c1", household_id: "h1", title: "New conversation", created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z" };
const msg = (id: string, role: "user" | "assistant", content: string) => ({
  id, role, content, provider: role === "assistant" ? "anthropic" : null, model: role === "assistant" ? "claude-opus-5-5" : null,
  input_tokens: role === "assistant" ? 1500 : null, output_tokens: role === "assistant" ? 40 : null, truncated: false,
  created_at: "2026-10-16T10:01:00Z",
});

function sse(events: Array<[string, unknown]>) {
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** Households h1 ("Rivera household") and h2 ("Chen household"); `chats` keyed by household id or "general". */
function backend(active = true, chats: Record<string, unknown[]> = {}) {
  return installFetch((c) => {
    if (c.url === `${API}/me/ai-providers`) return jsonResponse(providers(active));
    if (c.url === `${API}/households/h1`) return jsonResponse({ id: "h1", name: "Rivera household" });
    if (c.url === `${API}/households/h2`) return jsonResponse({ id: "h2", name: "Chen household" });
    if (c.url.startsWith(`${API}/chats?household_id=`)) return jsonResponse(chats[c.url.split("=")[1]!] ?? []);
    if (c.url === `${API}/chats` && c.method === "GET") return jsonResponse(chats.general ?? []);
    return undefined;
  });
}

describe("householdIdFromPath", () => {
  it("finds the household of household pages only", () => {
    const id = "ea889625-5503-44a9-aff7-15ff473c72b7";
    expect(householdIdFromPath(`/households/${id}`)).toBe(id);
    expect(householdIdFromPath(`/households/${id}/scenarios/x`)).toBe(id);
    expect(householdIdFromPath("/households")).toBeNull();
    expect(householdIdFromPath("/funds/abc")).toBeNull();
  });
});

describe("AssistantPanel", () => {
  it("asks for an AI provider before chatting", async () => {
    backend(false);
    render(<AssistantPanel householdId="h1" onHide={() => undefined} />);
    expect(await screen.findByText("Add an AI provider to use the assistant")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Settings → AI providers/ })).toHaveAttribute("href", "/settings/ai-providers");
    expect(screen.getByLabelText("Message")).toBeDisabled();
  });

  it("starts a household conversation and streams the reply", async () => {
    const user = userEvent.setup();
    let saved: unknown[] = [];
    const { calls } = installFetch((c) => {
      if (c.url === `${API}/me/ai-providers`) return jsonResponse(providers(true));
      if (c.url === `${API}/households/h1`) return jsonResponse({ id: "h1", name: "Rivera household" });
      if (c.url === `${API}/chats?household_id=h1`) return jsonResponse(saved);
      if (c.url === `${API}/chats` && c.method === "POST") return jsonResponse(chat, 201);
      if (c.url === `${API}/chats/c1/messages`) {
        saved = [{ ...chat, title: "When does cash run out?" }];
        return sse([
          ["delta", { text: "Month 4 " }],
          ["delta", { text: "is the first shortfall." }],
          ["done", { user_message: msg("m1", "user", "When does cash run out?"),
                     assistant_message: msg("m2", "assistant", "Month 4 is the first shortfall."),
                     title: "When does cash run out?" }],
        ]);
      }
      return undefined;
    });
    render(<AssistantPanel householdId="h1" onHide={() => undefined} />);
    expect(await screen.findByText("About Rivera household")).toBeInTheDocument();
    expect(await screen.findByText(/Answers use your Anthropic key · claude-opus-5-5/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "When does cash run out?{Enter}");

    const thread = await screen.findByRole("list", { name: "Messages" });
    expect(await within(thread).findByText("Month 4 is the first shortfall.")).toBeInTheDocument();
    expect(within(thread).getByText("claude-opus-5-5 · 1500 in / 40 out tokens")).toBeInTheDocument();
    expect(calls.find((c) => c.url === `${API}/chats` && c.method === "POST")?.body).toEqual({ household_id: "h1" });
    expect(calls.find((c) => c.url === `${API}/chats/c1/messages`)?.body).toEqual({ content: "When does cash run out?" });
    expect(screen.getByLabelText("Conversation")).toHaveDisplayValue("When does cash run out?");
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("reports a failed reply and keeps the message for a retry", async () => {
    const user = userEvent.setup();
    installFetch((c) => {
      if (c.url === `${API}/me/ai-providers`) return jsonResponse(providers(true));
      if (c.url === `${API}/chats`) return c.method === "POST" ? jsonResponse({ ...chat, household_id: null }, 201) : jsonResponse([]);
      if (c.url === `${API}/chats/c1/messages`) {
        return sse([["error", { code: "refusal", message: "The model declined to answer this message." }]]);
      }
      return undefined;
    });
    render(<AssistantPanel householdId={null} onHide={() => undefined} />);
    expect(await screen.findByText("General · no client data")).toBeInTheDocument();
    await screen.findByText(/Open a household to ask about a specific client/);
    await user.type(screen.getByLabelText("Message"), "Hello{Enter}");
    expect(await screen.findByText(/The model declined to answer this message\. Your message was not saved\./)).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");
  });

  it("opens a saved conversation", async () => {
    const user = userEvent.setup();
    installFetch((c) => {
      if (c.url === `${API}/chats/c1`) {
        return jsonResponse({ ...chat, title: "Capital calls", messages: [msg("m1", "user", "Next call?"), msg("m2", "assistant", "Month 3.")] });
      }
      if (c.url === `${API}/me/ai-providers`) return jsonResponse(providers(true));
      if (c.url === `${API}/households/h1`) return jsonResponse({ id: "h1", name: "Rivera household" });
      if (c.url === `${API}/chats?household_id=h1`) return jsonResponse([{ ...chat, title: "Capital calls" }]);
      return undefined;
    });
    render(<AssistantPanel householdId="h1" onHide={() => undefined} />);
    await screen.findByRole("option", { name: "Capital calls" });
    await user.selectOptions(screen.getByLabelText("Conversation"), "c1");
    const thread = await screen.findByRole("list", { name: "Messages" });
    expect(within(thread).getByText("Next call?")).toBeInTheDocument();
    expect(within(thread).getByText("Month 3.")).toBeInTheDocument();
  });

  it("follows the page to another household and can be minimized", async () => {
    const user = userEvent.setup();
    const onHide = vi.fn();
    backend(true, { h1: [{ ...chat, title: "Capital calls" }], h2: [{ ...chat, id: "c2", household_id: "h2", title: "Tax bill" }] });
    const { rerender } = render(<AssistantPanel householdId="h1" onHide={onHide} />);
    expect(await screen.findByRole("option", { name: "Capital calls" })).toBeInTheDocument();
    rerender(<AssistantPanel householdId="h2" onHide={onHide} />);
    expect(await screen.findByText("About Chen household")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Tax bill" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Capital calls" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Minimize assistant" }));
    expect(onHide).toHaveBeenCalled();
  });
});
