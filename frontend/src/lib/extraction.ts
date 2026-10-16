/** Display helpers for how a document was processed (extraction method + whose credentials were used). */
import type { JobOut } from "@/lib/types";

export const PROVIDER_LABELS: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI" };

export function providerLabel(provider: string | null | undefined): string | null {
  if (!provider) return null;
  return PROVIDER_LABELS[provider.toLowerCase()] ?? provider;
}

type JobLike = Pick<JobOut, "extraction_method" | "provider" | "model"> & { credential_source?: string | null };

/**
 * Human label for the extraction method of a processing job, e.g.
 * "Your OpenAI key · gpt-x", "Server provider · Anthropic model", "Rule-based (no LLM key available)".
 * Returns null when nothing is known yet (e.g. a queued job).
 *
 * `credential_source` is "user_byok" | "server" | "injected" | "none" (null for old jobs); the provider, model and
 * extraction method come from their own JobOut fields.
 */
export function extractionMethodLabel(job: JobLike): string | null {
  const source = (job.credential_source ?? "").trim().toLowerCase();
  const provider = providerLabel(job.provider);
  const model = job.model ?? "";
  const withModel = (base: string) => (model ? `${base} · ${model}` : base);

  switch (source) {
    case "user_byok":
      return withModel(`Your ${provider ?? "AI provider"} key`);
    case "server": {
      const detail = [provider, model].filter(Boolean).join(" ");
      return detail ? `Server provider · ${detail}` : "Server provider";
    }
    case "injected":
      return "Test provider";
    case "none":
      return "Rule-based (no LLM key available)";
  }
  // Older jobs without credential_source.
  if (job.extraction_method === "rule_based") return "Rule-based (no LLM)";
  if (job.extraction_method === "manual") return "Manual entry";
  if (job.extraction_method === "llm") return withModel(provider ? `LLM (${provider})` : "LLM");
  if (job.extraction_method) return job.extraction_method;
  return null;
}
