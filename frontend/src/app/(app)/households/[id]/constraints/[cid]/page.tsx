"use client";

import { useParams } from "next/navigation";
import { ConstraintReview } from "@/components/constraints/ConstraintReview";
import { useHousehold } from "@/components/household/HouseholdContext";

export default function ConstraintDetailPage() {
  const { cid } = useParams<{ cid: string }>();
  const { household, canEdit } = useHousehold();
  return <ConstraintReview constraintId={cid} householdId={household.id} canEdit={canEdit} />;
}
