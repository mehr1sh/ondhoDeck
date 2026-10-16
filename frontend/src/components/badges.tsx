"use client";

import { Badge, type BadgeTone } from "@/components/ui";
import { humanize } from "@/lib/format";

const DOC_TONES: Record<string, BadgeTone> = {
  pending_upload: "neutral",
  uploaded: "info",
  queued: "info",
  processing: "info",
  extracted: "success",
  failed: "danger",
  deleted: "neutral",
};

export function DocumentStatusBadge({ status }: { status: string }) {
  return <Badge tone={DOC_TONES[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

const JOB_TONES: Record<string, BadgeTone> = { queued: "info", running: "info", succeeded: "success", failed: "danger" };
export function JobStatusBadge({ status }: { status: string }) {
  return <Badge tone={JOB_TONES[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

const REVIEW_TONES: Record<string, BadgeTone> = {
  needs_review: "warning",
  confirmed: "success",
  edited: "info",
  rejected: "danger",
};
export function ReviewStatusBadge({ status }: { status: string }) {
  return <Badge tone={REVIEW_TONES[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

const SOURCE_LABELS: Record<string, { label: string; tone: BadgeTone; title: string }> = {
  source_backed: { label: "Source-backed", tone: "success", title: "Extracted from an uploaded contract with a cited quote" },
  synthetic_document: {
    label: "Synthetic document",
    tone: "warning",
    title: "Extracted from a synthetic demo document, not a real contract",
  },
  user_confirmed: { label: "User-confirmed", tone: "info", title: "Value entered or confirmed by a reviewer" },
  scenario_assumption: {
    label: "Scenario assumption",
    tone: "neutral",
    title: "A modelling assumption, not a contract term",
  },
};
export function SourceTypeBadge({ sourceType }: { sourceType: string }) {
  const s = SOURCE_LABELS[sourceType];
  return (
    <Badge tone={s?.tone ?? "neutral"} title={s?.title}>
      {s?.label ?? humanize(sourceType)}
    </Badge>
  );
}

export function QuoteVerifiedBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <Badge tone="success" title="The evidence quote was found verbatim in the document text">
      Quote verified
    </Badge>
  ) : (
    <Badge tone="danger" title="The evidence quote could not be matched to the document text">
      Quote unverified
    </Badge>
  );
}

const CONF_TONES: Record<string, BadgeTone> = { high: "success", medium: "warning", low: "danger" };
export function ConfidenceBadge({ confidence }: { confidence: string }) {
  return <Badge tone={CONF_TONES[confidence.toLowerCase()] ?? "neutral"}>{humanize(confidence)} confidence</Badge>;
}

const EXPORT_TONES: Record<string, BadgeTone> = { queued: "info", running: "info", ready: "success", failed: "danger" };
export function ExportStatusBadge({ status }: { status: string }) {
  return <Badge tone={EXPORT_TONES[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

const REC_TONES: Record<string, BadgeTone> = { proposed: "neutral", approved: "success", rejected: "danger" };
export function RecommendationStatusBadge({ status }: { status: string }) {
  return <Badge tone={REC_TONES[status] ?? "neutral"}>{humanize(status)}</Badge>;
}

export function AssumptionBadge() {
  return (
    <Badge tone="neutral" title="A modelling assumption you control, not a fact from a contract">
      Assumption
    </Badge>
  );
}

export const VALUE_KIND_INFO: Record<string, { label: string; title: string }> = {
  maximum: {
    label: "Maximum (cap)",
    title: "A limit the counterparty may fill less of (or not at all). It is not a guaranteed payout.",
  },
  minimum: { label: "Minimum", title: "A floor: at least this value applies (e.g. a minimum notice period)." },
  exact: { label: "Exact", title: "The clause states this value exactly." },
  range: { label: "Range", title: "The clause gives a range between the lower and upper bound." },
  qualitative: { label: "Qualitative", title: "The clause has no numeric value." },
};

export function ValueKindBadge({ valueKind }: { valueKind: string | null | undefined }) {
  if (!valueKind) return null;
  const info = VALUE_KIND_INFO[valueKind];
  return (
    <Badge tone={valueKind === "maximum" ? "info" : "neutral"} title={info?.title}>
      {info?.label ?? humanize(valueKind)}
    </Badge>
  );
}

export function AmbiguousBadge({ ambiguous }: { ambiguous: boolean | undefined }) {
  if (!ambiguous) return null;
  return (
    <Badge tone="warning" title="The clause contains discretion or conditions that were not fully captured">
      Ambiguous
    </Badge>
  );
}

export function ValidationIssuesBadge({ issues }: { issues: Array<{ severity?: string }> | undefined }) {
  if (!issues || issues.length === 0) return null;
  const errors = issues.filter((i) => i.severity === "error").length;
  const n = issues.length;
  return (
    <Badge
      tone={errors > 0 ? "danger" : "warning"}
      title={`${n} automated validation ${n === 1 ? "issue" : "issues"}${errors ? `, ${errors} serious` : ""}. Open the constraint to review.`}
    >
      {n} validation {n === 1 ? "issue" : "issues"}
    </Badge>
  );
}

const CREDENTIAL_STATUS: Record<string, { label: string; tone: BadgeTone; title: string }> = {
  untested: { label: "Untested", tone: "neutral", title: "The key has not been tested since it was saved or changed" },
  valid: { label: "Valid", tone: "success", title: "The last connection test succeeded" },
  invalid: { label: "Invalid key", tone: "danger", title: "The provider rejected this key" },
  quota_exceeded: { label: "Quota exceeded", tone: "warning", title: "The provider account has no remaining quota" },
  error: { label: "Test error", tone: "danger", title: "The last connection test failed" },
};
export function CredentialStatusBadge({ status }: { status: string }) {
  const s = CREDENTIAL_STATUS[status];
  return (
    <Badge tone={s?.tone ?? "neutral"} title={s?.title}>
      {s?.label ?? humanize(status)}
    </Badge>
  );
}
