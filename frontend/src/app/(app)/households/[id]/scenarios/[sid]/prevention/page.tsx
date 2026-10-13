"use client";

import { useParams } from "next/navigation";
import { PreventionView } from "@/components/prevention/PreventionView";
import { useHousehold } from "@/components/household/HouseholdContext";

export default function PreventionPage() {
  const { sid } = useParams<{ sid: string }>();
  const { household, canEdit } = useHousehold();
  return <PreventionView householdId={household.id} scenarioId={sid} currency={household.reporting_currency} canEdit={canEdit} />;
}
