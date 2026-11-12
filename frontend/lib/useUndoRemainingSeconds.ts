"use client";

import { useEffect, useState } from "react";

export const UNDO_WINDOW_SECONDS = 10 * 60;

/** Track the remaining undo window without keeping an interval after expiry. */
export function useUndoRemainingSeconds(decidedAt: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!decidedAt) return undefined;
    const decidedAtMs = Date.parse(decidedAt);
    const expiresAt = decidedAtMs + UNDO_WINDOW_SECONDS * 1000;
    if (!Number.isFinite(decidedAtMs) || expiresAt <= Date.now()) {
      setNow(Date.now());
      return undefined;
    }
    const timer = window.setInterval(() => {
      const currentTime = Date.now();
      setNow(currentTime);
      if (currentTime >= expiresAt) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [decidedAt]);

  if (!decidedAt) return null;
  const decidedAtMs = Date.parse(decidedAt);
  if (!Number.isFinite(decidedAtMs)) return null;
  return Math.max(
    0,
    Math.min(UNDO_WINDOW_SECONDS, UNDO_WINDOW_SECONDS - Math.floor((now - decidedAtMs) / 1000)),
  );
}
