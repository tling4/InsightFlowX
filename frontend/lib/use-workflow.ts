"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "./api";
import type { WorkflowCreate, WorkflowListItem } from "@/types/api";
import type { WorkflowDetail } from "@/types/workflow";

export function useWorkflows() {
  return useQuery<WorkflowListItem[]>({
    queryKey: ["workflows"],
    queryFn: async () => {
      const res = await api.get("/workflows");
      return res.data;
    },
  });
}

export function useWorkflow(id: string) {
  return useQuery<WorkflowDetail>({
    queryKey: ["workflow", id],
    queryFn: async () => {
      const res = await api.get(`/workflows/${id}`);
      return res.data;
    },
    enabled: !!id,
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: WorkflowCreate) => {
      const res = await api.post("/workflows", data);
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/workflows/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useStartWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await api.post(`/workflows/${id}/start`);
      return res.data;
    },
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["workflow", id] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useRetryNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ workflowId, node }: { workflowId: string; node: string }) => {
      const res = await api.post(`/workflows/${workflowId}/retry/${node}`);
      return res.data;
    },
    onSuccess: (_data, { workflowId }) => {
      qc.invalidateQueries({ queryKey: ["workflow", workflowId] });
    },
  });
}
