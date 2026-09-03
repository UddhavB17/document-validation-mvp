"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";

// These hooks are the frontend's cache and polling boundary. Components use
// them instead of coordinating fetches or invalidating related screens.
const APPLICATION_REVIEW_POLL_STATUSES = new Set(["uploaded", "processing", "ocr_completed"]);
const PROGRESS_POLL_STATUSES = new Set(["queued", "processing"]);

function isApplicationReviewPollingStatus(status: unknown): boolean {
  return APPLICATION_REVIEW_POLL_STATUSES.has(String(status ?? ""));
}

function isProgressPollingStatus(status: unknown): boolean {
  return PROGRESS_POLL_STATUSES.has(String(status ?? ""));
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 });
}

export function useWorklist() {
  return useQuery({ queryKey: ["worklist"], queryFn: api.worklist, refetchInterval: 10000 });
}

export function useActivityToday() {
  return useQuery({ queryKey: ["activityToday"], queryFn: api.activityToday });
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
    refetchInterval: (query) => isApplicationReviewPollingStatus(query.state.data?.application?.status) ? 2000 : false,
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
        queryClient.invalidateQueries({ queryKey: ["applicationReview", applicationId] }),
        queryClient.invalidateQueries({ queryKey: ["worklist"] }),
      ]);
    },
  });
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
