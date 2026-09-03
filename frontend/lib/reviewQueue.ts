export const REVIEW_QUEUE_STORAGE_KEY = "dmef_review_queue";

export type ReviewQueueSnapshot = {
  caseIds: number[];
  position: number;
};

function normalizeCaseIds(caseIds: number[]): number[] {
  return Array.from(new Set(caseIds.filter((caseId) => Number.isInteger(caseId) && caseId > 0)));
}

function normalizePosition(position: number, caseCount: number): number {
  if (caseCount === 0 || !Number.isInteger(position)) {
    return 0;
  }
  return Math.min(Math.max(position, 0), caseCount - 1);
}

export function startReviewQueue(caseIds: number[], position = 0): ReviewQueueSnapshot {
  const snapshot: ReviewQueueSnapshot = {
    caseIds: normalizeCaseIds(caseIds),
    position: 0,
  };
  snapshot.position = normalizePosition(position, snapshot.caseIds.length);

  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.setItem(REVIEW_QUEUE_STORAGE_KEY, JSON.stringify(snapshot));
    } catch {
      // Session storage can be unavailable in privacy-restricted browser contexts.
    }
  }

  return snapshot;
}

export function readReviewQueue(): ReviewQueueSnapshot | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.sessionStorage.getItem(REVIEW_QUEUE_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isReviewQueueSnapshot(parsed)) {
      return null;
    }
    const caseIds = normalizeCaseIds(parsed.caseIds);
    return { caseIds, position: normalizePosition(parsed.position, caseIds.length) };
  } catch {
    return null;
  }
}

export function updateReviewQueuePosition(position: number): ReviewQueueSnapshot | null {
  const current = readReviewQueue();
  if (!current) {
    return null;
  }
  return startReviewQueue(current.caseIds, position);
}

function isReviewQueueSnapshot(value: unknown): value is ReviewQueueSnapshot {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as { caseIds?: unknown; position?: unknown };
  return (
    Array.isArray(candidate.caseIds) &&
    candidate.caseIds.every((caseId) => typeof caseId === "number" && Number.isInteger(caseId)) &&
    typeof candidate.position === "number" &&
    Number.isInteger(candidate.position)
  );
}
