"use client";

import { useRouter } from "next/navigation";
import { Card, PageHeader } from "@/components/ui";
import { HouseholdForm } from "@/components/household/HouseholdForm";
import { useToast } from "@/components/Toast";
import { endpoints } from "@/lib/endpoints";

export default function NewHouseholdPage() {
  const router = useRouter();
  const toast = useToast();
  return (
    <div>
      <PageHeader title="Create household" description="You become the owner of the household you create." />
      <Card>
        <HouseholdForm
          submitLabel="Create household"
          onSubmit={async (body) => {
            const h = await endpoints.createHousehold(body);
            toast.success("Household created");
            router.push(`/households/${h.id}/profile`);
          }}
        />
      </Card>
    </div>
  );
}
