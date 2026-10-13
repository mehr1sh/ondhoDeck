"use client";

import { useParams } from "next/navigation";
import { ScenarioEditor } from "@/components/scenarios/ScenarioEditor";
import { useHousehold } from "@/components/household/HouseholdContext";

export default function ScenarioPage() {
  const { sid } = useParams<{ sid: string }>();
  const { household, canEdit } = useHousehold();
  return (
    <ScenarioEditor
      key={sid}
      householdId={household.id}
      scenarioId={sid}
      canEdit={canEdit}
      reportingCurrency={household.reporting_currency}
    />
  );
}
