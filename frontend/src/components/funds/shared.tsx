"use client";

import { Badge } from "@/components/ui";
import { humanize } from "@/lib/format";
import type { FirmRole, FundType } from "@/lib/types";

export const FUND_TYPE_LABELS: Record<FundType, string> = {
  non_traded_reit: "Non-traded REIT",
  interval_fund: "Interval fund",
  private_fund: "Private fund",
  other: "Other",
};

export function fundTypeLabel(t: string): string {
  return FUND_TYPE_LABELS[t as FundType] ?? humanize(t);
}

export function MetadataStatusBadge({ status }: { status: string }) {
  return status === "verified" ? (
    <Badge tone="success" title="A reviewer verified the fund's identifying details">
      Verified
    </Badge>
  ) : (
    <Badge tone="warning" title="Identifying details have not been verified by a reviewer">
      Needs review
    </Badge>
  );
}

export function FundStatusBadge({ status }: { status: string }) {
  return status === "archived" ? <Badge>Archived</Badge> : null;
}

export function canReviewLibrary(role: FirmRole | string | null | undefined): boolean {
  return role === "reviewer" || role === "admin";
}

export const ROLE_DESCRIPTIONS: Record<FirmRole, string> = {
  advisor: "Reads the Fund Library, adds funds and documents, and links household holdings to library funds.",
  reviewer: "Everything an advisor can do, plus approving, rejecting, editing and superseding library terms.",
  admin: "Everything a reviewer can do, plus managing firm members and renaming the firm.",
};

/** Local calendar date as YYYY-MM-DD. */
export function todayIso(now = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
