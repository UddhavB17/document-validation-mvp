"use client";

import { useEffect, useState } from "react";

import { api, ZipPreparationProgress } from "@/lib/api";

export function useZipPreparation(packageId: string | null) {
  const [progress, setProgress] = useState<ZipPreparationProgress | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    if (!packageId) {
      setProgress(null);
      setPollError(null);
      return;
    }

    let active = true;
    const interval = setInterval(async () => {
      try {
        const nextProgress = await api.getZipPreparationProgress(packageId);
        if (!active) return;
        setProgress(nextProgress);
        if (nextProgress.status === "prepared" || nextProgress.status === "failed") {
          clearInterval(interval);
        }
      } catch (error) {
        if (!active) return;
        clearInterval(interval);
        setPollError(error instanceof Error ? error.message : "Failed to get preparation progress");
      }
    }, 2000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [packageId]);

  return { progress, pollError };
}
