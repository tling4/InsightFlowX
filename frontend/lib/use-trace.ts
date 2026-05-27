"use client";

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import type { TraceLink } from "@/types/trace";

export function useTraceLinks(workflowId: string, enabled = true) {
  return useQuery<TraceLink[]>({
    queryKey: ["trace-links", workflowId],
    queryFn: async () => {
      const res = await api.get(`/workflows/${workflowId}/trace`);
      return res.data;
    },
    enabled: !!workflowId && enabled,
  });
}
