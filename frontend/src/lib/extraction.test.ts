import { describe, expect, it } from "vitest";
import { extractionMethodLabel } from "./extraction";

const job = (extra: Record<string, unknown>) => ({ extraction_method: "llm", provider: null, model: null, ...extra });

describe("extractionMethodLabel", () => {
  it("labels the user's own key with provider and model", () => {
    expect(extractionMethodLabel(job({ credential_source: "user_byok", provider: "openai", model: "gpt-x" }))).toBe(
      "Your OpenAI key · gpt-x",
    );
    expect(extractionMethodLabel(job({ credential_source: "user_byok", provider: "anthropic", model: null }))).toBe(
      "Your Anthropic key",
    );
  });

  it("labels the server provider", () => {
    expect(extractionMethodLabel(job({ credential_source: "server", provider: "anthropic", model: "m-1" }))).toBe(
      "Server provider · Anthropic m-1",
    );
    expect(extractionMethodLabel(job({ credential_source: "server" }))).toBe("Server provider");
  });

  it("labels rule-based and test extraction", () => {
    expect(extractionMethodLabel(job({ credential_source: "none", extraction_method: "rule_based" }))).toBe(
      "Rule-based (no LLM key available)",
    );
    expect(extractionMethodLabel(job({ credential_source: "injected" }))).toBe("Test provider");
  });

  it("falls back to extraction_method for old jobs", () => {
    expect(extractionMethodLabel(job({ credential_source: null, extraction_method: "rule_based" }))).toBe("Rule-based (no LLM)");
    expect(extractionMethodLabel(job({ extraction_method: null }))).toBeNull();
  });
});
