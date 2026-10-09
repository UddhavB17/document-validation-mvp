"use client";

import { useEffect, useState } from "react";

import { fetchEvidenceImageBlob } from "@/lib/evidenceImage";

export function EvidencePageImage({
  applicationId,
  pageNumber,
  highlight,
  alt,
  className,
  onReady,
  onError,
}: {
  applicationId: number;
  pageNumber: number;
  highlight?: string;
  alt: string;
  className?: string;
  onReady?: () => void;
  onError?: () => void;
}) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setSrc(null);
    void fetchEvidenceImageBlob(applicationId, pageNumber, highlight)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setSrc(url);
        onReady?.();
      })
      .catch(() => {
        if (!cancelled) {
          onError?.();
        }
      });
    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
    // onReady/onError intentionally omitted — callers often pass inline handlers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId, pageNumber, highlight]);

  if (!src) {
    return null;
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} className={className} />
  );
}
