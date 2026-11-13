"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  adminCreateUserRequest,
  adminDeleteUserRequest,
  adminListUsersRequest,
  adminResetPasswordRequest,
  adminUpdateUserRequest,
  api,
  fetchApplicationStatus,
  fetchOpsApplication,
  fetchOpsWorklist,
  fetchOpsTATWorklist,
  fetchOpsWorkflow,
  fetchOpsTatMetrics,
  fetchCurrentUser,
  opsWorkflowApi,
} from "./api";

// These hooks are the frontend's cache and polling boundary. Components use
// them instead of coordinating fetches or invalidating related screens.
//
// Polling diet (contracts §8): while an application is processing, the only
// repeating request from a review screen is
// GET /review/applications/{id}/status (2 s) — plus
// GET /upload/{id}/progress on upload-adjacent surfaces. The full review
// (GET /review/applications/{id}) and the ops payload
// (GET /ops/applications/{id}) are fetched once and refetched manually or
// when the status hook reports a terminal state.
// In-flight statuses that keep the lightweight /status poll alive. The API
// reports `processing` while a run is active; every other state is terminal,
// stops the 2 s poll, and triggers a single full-payload refetch.
const APPLICATION_REVIEW_POLL_STATUSES = new Set(["processing"]);
const PROGRESS_POLL_STATUSES = new Set(["queued", "processing"]);

export const STATUS_POLL_INTERVAL_MS = 2000;

export function isApplicationReviewPollingStatus(status: unknown): boolean {
  return APPLICATION_REVIEW_POLL_STATUSES.has(String(status ?? ""));
}

function isProgressPollingStatus(status: unknown): boolean {
  return PROGRESS_POLL_STATUSES.has(String(status ?? ""));
}

/** Interval for the lightweight /status poll: 2 s while processing, off when terminal. */
export function getStatusPollInterval(status: unknown): number | false {
  return isApplicationReviewPollingStatus(status) ? STATUS_POLL_INTERVAL_MS : false;
}

/** The full review is fetched once; callers refetch on demand or on status change. */
export function getApplicationReviewPollInterval(): false {
  return false;
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 });
}

export function useCurrentUser() {
  return useQuery({ queryKey: ["currentUser"], queryFn: fetchCurrentUser, staleTime: 60000 });
}

export function useWorklist() {
  return useQuery({ queryKey: ["worklist"], queryFn: api.worklist, refetchInterval: 10000 });
}

export function useOpsWorklist(view = "all") {
  return useQuery({ queryKey: ["opsWorklist", view], queryFn: () => fetchOpsTATWorklist(view), refetchInterval: 10000 });
}

export function useOpsWorkflow(applicationId: number | null) {
  return useQuery({
    queryKey: ["opsWorkflow", applicationId],
    queryFn: () => {
      if (applicationId === null) throw new Error("Application ID is required");
      return fetchOpsWorkflow(applicationId);
    },
    enabled: applicationId !== null,
  });
}

export function useOpsTatMetrics() {
  return useQuery({ queryKey: ["opsTatMetrics"], queryFn: fetchOpsTatMetrics });
}

function useOpsWorkflowMutation<T>(mutationFn: (value: T) => Promise<unknown>, applicationId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["opsWorklist"] }),
        queryClient.invalidateQueries({ queryKey: ["opsWorkflow", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["opsTatMetrics"] }),
      ]);
    },
  });
}

export function useClaimOpsCase(applicationId: number) {
  return useOpsWorkflowMutation(() => opsWorkflowApi.claim(applicationId), applicationId);
}

export function useReleaseOpsCase(applicationId: number) {
  return useOpsWorkflowMutation(() => opsWorkflowApi.release(applicationId), applicationId);
}

export function useReassignOpsCase(applicationId: number) {
  return useOpsWorkflowMutation((payload: { user_id: number; reason: string }) => opsWorkflowApi.reassign(applicationId, payload), applicationId);
}

export function useSaveOpsCheck(applicationId: number) {
  return useOpsWorkflowMutation((payload: { check_key: string; evidence_revision: string; status: string; note?: string }) =>
    opsWorkflowApi.saveCheck(applicationId, payload), applicationId);
}

export function useRequestOpsDocuments(applicationId: number) {
  return useOpsWorkflowMutation((payload: { message: string; items: string[]; follow_up_at?: string }) =>
    opsWorkflowApi.requestDocuments(applicationId, payload), applicationId);
}

export function useUpdateOpsDocumentItem(applicationId: number) {
  return useOpsWorkflowMutation((payload: { requestId: number; itemId: number; status: string; uploadedFileId?: number }) =>
    opsWorkflowApi.updateDocumentItem(applicationId, payload.requestId, payload.itemId, payload.status, payload.uploadedFileId), applicationId);
}

export function useReviewNextOpsCase() {
  return useOpsWorkflowMutation(() => opsWorkflowApi.next());
}

export function useActivityToday() {
  return useQuery({ queryKey: ["activityToday"], queryFn: api.activityToday });
}

/** Lightweight processing status; the only poller allowed on review screens. */
export function useApplicationStatus(applicationId: number | null) {
  return useQuery({
    queryKey: ["applicationStatus", applicationId],
    queryFn: () => {
      if (applicationId === null) {
        throw new Error("Application ID is required");
      }
      return fetchApplicationStatus(applicationId);
    },
    enabled: applicationId !== null,
    refetchInterval: (query) => getStatusPollInterval(query.state.data?.status),
    retry: false,
  });
}

export function useApplicationReview(applicationId: number | null) {
  return useQuery({
    queryKey: ["applicationReview", applicationId],
    queryFn: () => {
      if (applicationId === null) {
        throw new Error("Application ID is required");
      }
      return api.applicationReview(applicationId);
    },
    enabled: applicationId !== null,
    refetchInterval: getApplicationReviewPollInterval(),
  });
}

/** Operations payload; fetched once, refetched when status turns terminal. */
export function useOpsApplication(applicationId: number | null) {
  return useQuery({
    queryKey: ["opsApplication", applicationId],
    queryFn: () => {
      if (applicationId === null) {
        throw new Error("Application ID is required");
      }
      return fetchOpsApplication(applicationId);
    },
    enabled: applicationId !== null,
    refetchInterval: getApplicationReviewPollInterval(),
  });
}

export function useProgress(applicationId: number | null) {
  return useQuery({
    queryKey: ["progress", applicationId],
    queryFn: () => {
      if (applicationId === null) {
        throw new Error("Application ID is required");
      }
      return api.progress(applicationId);
    },
    enabled: applicationId !== null,
    refetchInterval: (query) =>
      isProgressPollingStatus(query.state.data?.operational_status ?? query.state.data?.status) ? 2000 : false,
    retry: false,
  });
}

export function useReprocessApplication(applicationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.reprocessApplication(applicationId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["progress", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["applicationStatus", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["applicationReview", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["opsApplication", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["worklist"] }),
      ]);
    },
  });
}

function useRecoveryMutation<TVariables>(
  applicationId: number,
  mutationFn: (variables: TVariables) => Promise<unknown>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["progress", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["applicationStatus", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["applicationReview", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["opsApplication", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["worklist"] }),
      ]);
    },
  });
}

export function useResumeApplication(applicationId: number) {
  return useRecoveryMutation<void>(applicationId, () => api.resumeApplication(applicationId));
}

export function useRestartApplication(applicationId: number) {
  return useRecoveryMutation<boolean>(applicationId, (fromCheckpoint: boolean) =>
    api.restartApplication(applicationId, fromCheckpoint),
  );
}

export function useCreateDecision(applicationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createDecision,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["applicationReview", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["worklist"] }),
        queryClient.invalidateQueries({ queryKey: ["activityToday"] }),
      ]);
    },
  });
}

export function useUndoDecision(applicationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.undoDecision,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["applicationReview", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["worklist"] }),
        queryClient.invalidateQueries({ queryKey: ["activityToday"] }),
      ]);
    },
  });
}

const BATCH_TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "rejected"]);

export function useBatchStatus(batchId: string | null) {
  return useQuery({
    queryKey: ["batchStatus", batchId],
    queryFn: () => {
      if (batchId === null) {
        throw new Error("Batch ID is required");
      }
      return api.batchStatus(batchId);
    },
    enabled: batchId !== null,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      const pending = items.some((item) => !BATCH_TERMINAL_STATUSES.has(String(item.status ?? "").toLowerCase()));
      return pending ? 3000 : false;
    },
    retry: false,
  });
}

export function useAdminUsers() {
  return useQuery({ queryKey: ["adminUsers"], queryFn: adminListUsersRequest });
}

export function useCreateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: adminCreateUserRequest,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["adminUsers"] });
    },
  });
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { userId: number; patch: { display_name?: string; role?: string; is_active?: boolean } }) =>
      adminUpdateUserRequest(payload.userId, payload.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["adminUsers"] });
    },
  });
}

export function useResetAdminPassword() {
  return useMutation({
    mutationFn: (payload: { userId: number; newPassword: string }) =>
      adminResetPasswordRequest(payload.userId, payload.newPassword),
  });
}

export function useDeleteAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => adminDeleteUserRequest(userId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["adminUsers"] });
    },
  });
}
