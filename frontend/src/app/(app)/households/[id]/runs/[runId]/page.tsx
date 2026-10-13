"use client";

import { useParams } from "next/navigation";
import { ErrorState, LoadingBlock } from "@/components/ui";
import { RunResults } from "@/components/runs/RunResults";
import { useHousehold } from "@/components/household/HouseholdContext";
import { endpoints } from "@/lib/endpoints";
import { useApiQuery } from "@/lib/hooks";

export default function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const { household } = useHousehold();
  const q = useApiQuery(() => endpoints.getRun(runId), [runId]);
  if (q.loading && !q.data) return <LoadingBlock rows={8} label="Loading run…" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.reload()} />;
  return <RunResults run={q.data} householdId={household.id} />;
}
