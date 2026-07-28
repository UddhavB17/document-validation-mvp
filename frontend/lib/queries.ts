"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";

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
    queryFn: () => api.applicationReview(applicationId as number),
    enabled: applicationId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.application?.status ?? "");
      return ["uploaded", "processing", "ocr_completed"].includes(status) ? 2000 : false;
    },
  });
}

export function useProgress(applicationId: number | null) {
  return useQuery({
    queryKey: ["progress", applicationId],
    queryFn: () => api.progress(applicationId as number),
    enabled: applicationId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.operational_status ?? query.state.data?.status ?? "");
      return ["queued", "processing"].includes(status) ? 2000 : false;
    },
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
