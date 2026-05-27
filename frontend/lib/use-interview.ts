"use client";

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import type { InterviewMessage } from "@/types/interview";

export function useInterviewHistory(workflowId: string) {
  return useQuery<InterviewMessage[]>({
    queryKey: ["interview-history", workflowId],
    queryFn: async () => {
      const res = await api.get(`/workflows/${workflowId}/interview/history`);
      return res.data;
    },
    enabled: !!workflowId,
  });
}
