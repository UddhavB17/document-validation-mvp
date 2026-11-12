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
    let inFlight = false;
    let finished = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const scheduleNext = () => {
      if (!isMounted || finished) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void poll(), 2000);
    };

    const poll = async () => {
      if (!isMounted || finished || inFlight) return;
      if (document.hidden) {
        scheduleNext();
        return;
      }
      inFlight = true;
      try {
        const updatedProgress = await api.getZipPreparationProgress(packageId);
        if (!isMounted) return;
        setProgress(updatedProgress);
        if (updatedProgress.status === "prepared" || updatedProgress.status === "failed") {
          finished = true;
        }
      } catch (error) {
        if (!isMounted) return;
        finished = true;
        setPollError(error instanceof Error ? error.message : "Failed to get preparation progress");
      } finally {
        inFlight = false;
        scheduleNext();
      }
    };

    const onVisibilityChange = () => {
      if (!document.hidden && !finished) {
        if (timer) clearTimeout(timer);
        void poll();
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    void poll();

    return () => {
      isMounted = false;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [packageId]);

  return { progress, pollError };
}
