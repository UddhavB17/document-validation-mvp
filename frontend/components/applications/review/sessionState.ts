export type ReviewIssueState = "Unopened" | "Viewed" | "Checked";
export type ReviewTaskState = "Unchecked" | "Checked";

export const REVIEW_STATE_EVENT = "dmef-review-state-change";
const STORAGE_PREFIX = "dmef-review-session-state";
const TASK_STORAGE_PREFIX = "dmef-review-task-state";

function storageKey(issueKey: string): string {
  return `${STORAGE_PREFIX}:${issueKey}`;
}

function taskStorageKey(applicationId: number, taskId: string): string {
  return `${TASK_STORAGE_PREFIX}:${applicationId}:${encodeURIComponent(taskId)}`;
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

export function markReviewIssueChecked(issueKey: string, applicationId?: number, taskIds: readonly string[] = []): void {
  setReviewIssueState(issueKey, "Checked");
  if (applicationId !== undefined) taskIds.forEach((taskId) => setReviewTaskChecked(applicationId, taskId, true));
}

export function getReviewTaskState(applicationId: number, taskId: string): ReviewTaskState {
  if (typeof window === "undefined") return "Unchecked";
  try {
    return window.sessionStorage.getItem(taskStorageKey(applicationId, taskId)) === "Checked" ? "Checked" : "Unchecked";
  } catch {
    return "Unchecked";
  }
}

function setReviewTaskState(applicationId: number, taskId: string, state: ReviewTaskState): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(taskStorageKey(applicationId, taskId), state);
  } catch {
    // Session storage can be unavailable in privacy-restricted contexts.
  }
  window.dispatchEvent(new CustomEvent(REVIEW_STATE_EVENT, {
    detail: { applicationId, taskId, state },
  }));
}

export function setReviewTaskChecked(applicationId: number, taskId: string, checked: boolean): void {
  setReviewTaskState(applicationId, taskId, checked ? "Checked" : "Unchecked");
}

export function getCheckedReviewTaskIds(applicationId: number, taskIds: readonly string[]): Set<string> {
  return new Set(taskIds.filter((taskId) => getReviewTaskState(applicationId, taskId) === "Checked"));
}

export function markReviewIssueCheckedWithTasks(issueKey: string, applicationId: number, taskIds: readonly string[] = []): void {
  markReviewIssueChecked(issueKey, applicationId, taskIds);
}
