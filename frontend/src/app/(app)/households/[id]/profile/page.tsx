"use client";

import { Notice } from "@/components/ui";
import { useHousehold } from "@/components/household/HouseholdContext";
import { AssetsSection, CashFlowsSection, EventsSection, LiabilitiesSection } from "@/components/profile/sections";

export default function ProfilePage() {
  const { household, canEdit } = useHousehold();
  return (
    <div className="space-y-5">
      {!canEdit && <Notice>You have view-only access to this household.</Notice>}
      {household.is_demo && (
        <Notice tone="warning" title="Synthetic demo data">
          The records below are synthetic and were generated for demonstration.
        </Notice>
      )}
      <AssetsSection householdId={household.id} canEdit={canEdit} />
      <LiabilitiesSection householdId={household.id} canEdit={canEdit} />
      <CashFlowsSection householdId={household.id} canEdit={canEdit} />
      <EventsSection householdId={household.id} canEdit={canEdit} />
    </div>
  );
}
