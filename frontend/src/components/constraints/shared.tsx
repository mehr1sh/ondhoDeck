"use client";

import { Badge } from "@/components/ui";
import { EMPTY, formatNumber } from "@/lib/format";
import type { ConstraintOut } from "@/lib/types";

export function isQualitative(c: Pick<ConstraintOut, "is_qualitative" | "value" | "lower_bound" | "upper_bound">) {
  return c.is_qualitative || (c.value === null && c.lower_bound === null && c.upper_bound === null);
}

export function ConstraintValue({ c }: { c: ConstraintOut }) {
  if (isQualitative(c)) return <Badge>qualitative</Badge>;
  const unit = c.unit ? ` ${c.unit}` : "";
  if (c.value !== null) return <span className="tabular-nums">{formatNumber(c.value, 4)}{unit}</span>;
  return (
    <span className="tabular-nums">
      {c.lower_bound !== null ? formatNumber(c.lower_bound, 4) : EMPTY}–{c.upper_bound !== null ? formatNumber(c.upper_bound, 4) : EMPTY}
      {unit}
    </span>
  );
}

