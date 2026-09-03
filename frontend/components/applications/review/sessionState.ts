export type ReviewIssueState = "Unopened" | "Viewed" | "Checked";

export const REVIEW_STATE_EVENT = "dmef-review-state-change";
const STORAGE_PREFIX = "dmef-review-session-state";

function storageKey(issueKey: string): string {
  return `${STORAGE_PREFIX}:${issueKey}`;
}

export function getReviewIssueState(issueKey: string): ReviewIssueState {
  if (typeof window === "undefined") return "Unopened";
  try {
    const value = window.sessionStorage.getItem(storageKey(issueKey));
    return value === "Viewed" || value === "Checked" ? value : "Unopened";
  } catch {
    return "Unopened";
  }
}

function setReviewIssueState(issueKey: string, nextState: ReviewIssueState): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(storageKey(issueKey), nextState);
  } catch {
    // The queue remains usable when storage is disabled or unavailable.
  }
  window.dispatchEvent(new CustomEvent(REVIEW_STATE_EVENT, { detail: { issueKey, state: nextState } }));
}

export function markReviewIssueViewed(issueKey: string): void {
  if (getReviewIssueState(issueKey) === "Checked") return;
  setReviewIssueState(issueKey, "Viewed");
}

export function markReviewIssueChecked(issueKey: string): void {
  setReviewIssueState(issueKey, "Checked");
}
