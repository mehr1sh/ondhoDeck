"use client";

import { useParams } from "next/navigation";
import { FundDetailView } from "@/components/funds/FundDetailView";

export default function FundPage() {
  const { fundId } = useParams<{ fundId: string }>();
  return <FundDetailView key={fundId} fundId={fundId} />;
}
