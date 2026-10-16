"use client";

import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { AiProviderSettings } from "@/components/ai/AiProviderSettings";
import { KeyActivity } from "@/components/ai/KeyActivity";

export default function AiProvidersPage() {
  return (
    <div className="space-y-5">
      <Link href="/settings" className="text-xs text-slate-600 hover:underline">
        ← Settings
      </Link>
      <PageHeader
        title="AI providers"
        description="Use your own Anthropic or OpenAI API key to extract contract constraints from uploaded documents. Every extracted constraint still needs your review."
      />
      <AiProviderSettings />
      <KeyActivity />
    </div>
  );
}
