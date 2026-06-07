"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "./api";
import type { WorkflowCreate, WorkflowListItem } from "@/types/api";
import type { WorkflowConfig, WorkflowDetail } from "@/types/workflow";

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
    // 运行中 15s 轮询兜底 SSE 丢失（如 workflow_complete 未到达），终态自动停止
    refetchInterval: (query) => (query.state.data?.status === "running" ? 15_000 : false),
    refetchOnWindowFocus: true,
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

export function useUpdateWorkflowTitle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) => {
      const res = await api.patch(`/workflows/${id}`, { title });
      return res.data;
    },
    onMutate: async ({ id, title }) => {
      const workflowKey = ["workflow", id] as const;
      const previousWorkflow = qc.getQueryData<WorkflowDetail>(workflowKey);
      const previousWorkflows = qc.getQueryData<WorkflowListItem[]>(["workflows"]);

      qc.setQueryData<WorkflowDetail | undefined>(workflowKey, (current) => (
        current ? { ...current, title } : current
      ));
      qc.setQueryData<WorkflowListItem[] | undefined>(["workflows"], (current) => (
        current?.map((item) => (item.id === id ? { ...item, title } : item))
      ));

      return { previousWorkflow, previousWorkflows };
    },
    onError: (_error, { id }, context) => {
      qc.setQueryData(["workflow", id], context?.previousWorkflow);
      qc.setQueryData(["workflows"], context?.previousWorkflows);
    },
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ["workflow", id] });
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
    mutationFn: async ({ id, config }: { id: string; config?: Partial<WorkflowConfig> }) => {
      // 可选 config body：让右侧面板用户编辑成为权威配置（覆盖 workflow.config）
      // 显式分支避免 axios 在 body=undefined 时仍发送 Content-Type 头
      const res = config
        ? await api.post(`/workflows/${id}/start`, config)
        : await api.post(`/workflows/${id}/start`);
      return res.data;
    },
    onSuccess: (_data, { id }) => {
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
