import type { ReactNode } from "react";
import { HouseholdFrame } from "@/components/household/HouseholdContext";

export default function HouseholdLayout({ children }: { children: ReactNode }) {
  return <HouseholdFrame>{children}</HouseholdFrame>;
}
