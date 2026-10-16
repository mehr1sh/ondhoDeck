import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API, errorResponse, installFetch, jsonResponse, makeAuthMock } from "@/test/utils";

const { auth } = vi.hoisted(() => ({ auth: {} as Record<string, unknown> }));
vi.mock("@/lib/supabase/client", () => ({ getSupabaseBrowserClient: () => ({ auth }) }));

import { AiProviderSettings, messageForCode } from "./AiProviderSettings";

const KEY = "sk-test-0123456789abcdefSECRET";

function cred(extra: Record<string, unknown> = {}) {
  return {
    provider: "openai",
    key_hint: "…CRET",
    model: null,
    is_active: true,
    status: "invalid",
    last_tested_at: "2026-10-16T00:00:00Z",
    last_error_code: null,
    last_error: null,
    updated_at: "2026-10-16T00:00:00Z",
    ...extra,
  };
}

function listing(credentials: unknown[] = [], extra: Record<string, unknown> = {}) {
  return {
    storage_available: true,
    storage_message: null,
    providers: [
      { provider: "anthropic", label: "Anthropic", default_model: "model-a" },
      { provider: "openai", label: "OpenAI", default_model: null },
    ],
    credentials,
    active_provider: null,
    server_fallback: { configured: false, provider: null, model: null },
    extraction_order: "Your active key if it is valid; otherwise the server provider; otherwise rule-based.",
    ...extra,
  };
}

/** In-memory Storage whose writes are recorded, installed as both localStorage and sessionStorage. */
function fakeStorage() {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    key: (i: number) => [...data.keys()][i] ?? null,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: vi.fn((k: string, v: string) => void data.set(k, String(v))),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
  };
}

let local: ReturnType<typeof fakeStorage>;
let session: ReturnType<typeof fakeStorage>;
const originals = {
  local: Object.getOwnPropertyDescriptor(window, "localStorage"),
  session: Object.getOwnPropertyDescriptor(window, "sessionStorage"),
};
beforeEach(() => {
  Object.assign(auth, makeAuthMock());
  local = fakeStorage();
  session = fakeStorage();
  Object.defineProperty(window, "localStorage", { value: local, configurable: true });
  Object.defineProperty(window, "sessionStorage", { value: session, configurable: true });
});
afterEach(() => {
  if (originals.local) Object.defineProperty(window, "localStorage", originals.local);
  else delete (window as { localStorage?: unknown }).localStorage;
  if (originals.session) Object.defineProperty(window, "sessionStorage", originals.session);
  else delete (window as { sessionStorage?: unknown }).sessionStorage;
});

function assertNoKeyLeak(calls: { url: string }[]) {
  expect(local.setItem).not.toHaveBeenCalled();
  expect(session.setItem).not.toHaveBeenCalled();
  expect(local.length).toBe(0);
  expect(session.length).toBe(0);
  expect(document.cookie).not.toContain(KEY);
  expect(window.location.href).not.toContain(KEY);
  for (const c of calls) expect(c.url).not.toContain(KEY);
  expect(document.body.textContent).not.toContain(KEY);
}

describe("AiProviderSettings", () => {
  it("sends the key in the body, clears the input after a successful save and never stores it", async () => {
    let saved = false;
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`)
        return jsonResponse(listing(saved ? [cred({ provider: "anthropic", status: "valid", model: "model-a" })] : []));
      if (c.method === "PUT" && c.url === `${API}/me/ai-providers/anthropic`) {
        saved = true;
        return jsonResponse({
          ok: true,
          code: "ok",
          message: "Connected.",
          credential: cred({ provider: "anthropic", status: "valid", model: "model-a" }),
        });
      }
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    const input = await screen.findByLabelText(/Anthropic API key/);
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "off");
    await user.type(input, KEY);
    expect(input).toHaveValue(KEY);
    await user.click(screen.getByRole("button", { name: /Save & test/ }));

    await screen.findByText("Connection works");
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({ api_key: KEY, model: "model-a", workspace_id: null, activate: true });
    expect(await screen.findByLabelText("Masked key")).toHaveTextContent("…CRET");
    assertNoKeyLeak(calls);
  });

  it("sends an Anthropic workspace ID, rejects malformed ones and explains workspace_required", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`) return jsonResponse(listing());
      if (c.method === "PUT" && c.url === `${API}/me/ai-providers/anthropic`)
        return jsonResponse({
          ok: false,
          code: "workspace_required",
          message: "This Anthropic API key is not scoped to a workspace.",
          credential: cred({ provider: "anthropic", status: "error", model: "model-a" }),
        });
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    const input = await screen.findByLabelText(/Anthropic API key/);
    const ws = screen.getByRole("textbox", { name: /Workspace ID/ });
    await user.type(ws, "workspace-1");
    await user.type(input, KEY);
    await user.click(screen.getByRole("button", { name: /Save & test/ }));
    expect(await screen.findByText("Check the workspace ID")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    await user.clear(ws);
    await user.type(ws, "wrkspc_01ABCdef234");
    await user.type(input, KEY);
    await user.click(screen.getByRole("button", { name: /Save & test/ }));
    expect(await screen.findByText("Workspace ID needed")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toMatchObject({ api_key: KEY, workspace_id: "wrkspc_01ABCdef234" });
    assertNoKeyLeak(calls);
  });

  it("clears the key after a failed save and explains an invalid key", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`) return jsonResponse(listing());
      if (c.method === "PUT" && c.url === `${API}/me/ai-providers/anthropic`)
        return jsonResponse({ ok: false, code: "invalid_key", message: "Rejected by provider.", credential: cred({ provider: "anthropic" }) });
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    const input = await screen.findByLabelText(/Anthropic API key/);
    await user.type(input, KEY);
    await user.click(screen.getByRole("button", { name: /Save & test/ }));
    expect(input).toHaveValue("");
    expect(await screen.findByText("Invalid key")).toBeInTheDocument();
    assertNoKeyLeak(calls);
  });

  it("clears the key when the request errors (rate limited)", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`) return jsonResponse(listing());
      if (c.method === "PUT") return errorResponse(429, "rate_limited", "Too many requests.");
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    const input = await screen.findByLabelText(/Anthropic API key/);
    await user.type(input, KEY);
    await user.click(screen.getByRole("button", { name: /Save & test/ }));
    expect(await screen.findByText("Rate limited")).toBeInTheDocument();
    expect(input).toHaveValue("");
    assertNoKeyLeak(calls);
  });

  it("disables the form and shows the storage message when key storage is unavailable", async () => {
    installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`)
        return jsonResponse(listing([], { storage_available: false, storage_message: "Key storage is disabled: no keys configured." }));
      return undefined;
    });
    render(<AiProviderSettings />);
    expect(await screen.findByText(/no keys configured/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Anthropic API key/)).toBeDisabled();
    expect(screen.getByRole("button", { name: /Save & test/ })).toBeDisabled();
  });

  it("loads OpenAI models for a stored key and saves the chosen model", async () => {
    const { calls } = installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`)
        return jsonResponse(listing([cred({ status: "error", last_error_code: "model_required" })], { active_provider: "openai" }));
      if (c.method === "GET" && c.url === `${API}/me/ai-providers/openai/models`)
        return jsonResponse({ provider: "openai", models: ["gpt-x", "gpt-y"] });
      if (c.method === "PATCH" && c.url === `${API}/me/ai-providers/openai`) return jsonResponse(cred({ model: "gpt-y", status: "untested" }));
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    await user.click(await screen.findByRole("button", { name: "Load models" }));
    await user.selectOptions(await screen.findByLabelText("Available models"), "gpt-y");
    await user.click(screen.getByRole("button", { name: "Save model" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ model: "gpt-y" });
  });

  it("asks to replace the key when it cannot be decrypted", async () => {
    installFetch((c) => {
      if (c.method === "GET" && c.url === `${API}/me/ai-providers`)
        return jsonResponse(listing([cred({ provider: "anthropic", model: "model-a" })], { active_provider: "anthropic" }));
      if (c.method === "POST" && c.url === `${API}/me/ai-providers/anthropic/test`)
        return errorResponse(409, "credential_unreadable", "Replace the key.");
      return undefined;
    });
    const user = userEvent.setup();
    render(<AiProviderSettings />);
    await user.click(await screen.findByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("Stored key cannot be read")).toBeInTheDocument();
    expect(screen.getByLabelText(/New Anthropic API key/)).toBeInTheDocument();
  });

  it("maps quota and model_required codes to clear messages", () => {
    expect(messageForCode("quota_exceeded").title).toBe("Quota exceeded");
    expect(messageForCode("model_required").title).toBe("Choose a model");
    expect(messageForCode("weird", "Oops").message).toBe("Oops");
  });
});
