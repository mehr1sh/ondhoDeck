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
