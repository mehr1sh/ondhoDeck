"use client";

import { useParams } from "next/navigation";
import { StressView } from "@/components/stress/StressView";
import { useHousehold } from "@/components/household/HouseholdContext";

export default function StressPage() {
  const { sid } = useParams<{ sid: string }>();
  const { household, canEdit } = useHousehold();
  return <StressView householdId={household.id} scenarioId={sid} currency={household.reporting_currency} canEdit={canEdit} />;
}
