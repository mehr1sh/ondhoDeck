"use client";

import { useState } from "react";
import { useToast } from "@/components/Toast";
import { resolveApiUrl } from "@/lib/api";
import { endpoints } from "@/lib/endpoints";
import { describeError } from "@/lib/hooks";

/** Opens a ready export's signed URL in a new tab. `downloading` is the id of the export being fetched. */
export function useExportDownload() {
  const toast = useToast();
  const [downloading, setDownloading] = useState<string | null>(null);

  const download = async (id: string) => {
    setDownloading(id);
    try {
      const signed = await endpoints.downloadExport(id);
      window.open(resolveApiUrl(signed.url), "_blank", "noopener,noreferrer");
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    } finally {
      setDownloading(null);
    }
  };

  return { downloading, download };
}
