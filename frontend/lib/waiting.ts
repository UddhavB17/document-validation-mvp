/** Compact waiting label from an ISO timestamp (e.g. "2h 41m", "54m"). */
export function formatWaitingSince(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) {
    return "—";
  }
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) {
    return "—";
  }
  const diffMs = Math.max(0, nowMs - then);
  const totalMinutes = Math.floor(diffMs / 60000);
  if (totalMinutes < 1) {
    return "<1m";
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) {
    return `${minutes}m`;
  }
  if (hours < 48) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d`;
}
