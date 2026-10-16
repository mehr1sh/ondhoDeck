"use client";

import { useParams } from "next/navigation";
import { BlindSpotPanel } from "@/components/blindspots/BlindSpotPanel";
import { ScenarioEditor } from "@/components/scenarios/ScenarioEditor";
import { useHousehold } from "@/components/household/HouseholdContext";

export default function ScenarioPage() {
  const { sid } = useParams<{ sid: string }>();
  const { household, canEdit } = useHousehold();
  return (
    <div className="space-y-6">
      <ScenarioEditor
        key={sid}
        householdId={household.id}
        scenarioId={sid}
        canEdit={canEdit}
        reportingCurrency={household.reporting_currency}
      />
      {sid !== "new" && (
        <BlindSpotPanel
          key={`bs-${sid}`}
          householdId={household.id}
          scenarioId={sid}
          currency={household.reporting_currency}
          canEdit={canEdit}
        />
      )}
    </div>
  );
}
