"use client";

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import type { TraceLink } from "@/types/trace";

export function useTraceLinks(workflowId: string, enabled = true, executionAttempt?: number) {
  return useQuery<TraceLink[]>({
    queryKey: ["trace-links", workflowId, executionAttempt],
    queryFn: async () => {
      const params = executionAttempt != null ? `?execution_attempt=${executionAttempt}` : "";
      const res = await api.get(`/workflows/${workflowId}/trace${params}`);
      return res.data;
    },
    enabled: !!workflowId && enabled,
  });
}
