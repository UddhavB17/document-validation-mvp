"use client";

import { useEffect, useState } from "react";

import { api, ZipPreparationProgress } from "@/lib/api";

// Polls the backend-owned ZIP preparation job until it finishes or fails.
export function useZipPreparation(packageId: string | null) {
  const [progress, setProgress] = useState<ZipPreparationProgress | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    if (!packageId) {
      setProgress(null);
      setPollError(null);
      return;
    }

    let isMounted = true;
    const interval = setInterval(async () => {
      try {
        const updatedProgress = await api.getZipPreparationProgress(packageId);
        if (!isMounted) return;
        setProgress(updatedProgress);
        if (updatedProgress.status === "prepared" || updatedProgress.status === "failed") {
          clearInterval(interval);
        }
      } catch (error) {
        if (!isMounted) return;
        clearInterval(interval);
        setPollError(error instanceof Error ? error.message : "Failed to get preparation progress");
      }
    }, 2000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [packageId]);

  return { progress, pollError };
}
