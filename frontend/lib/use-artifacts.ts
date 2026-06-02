"use client";

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import type { ArtifactListItem, ArtifactDetail } from "@/types/artifact";

export function useArtifacts(workflowId: string, enabled = true, executionAttempt?: number) {
  return useQuery<ArtifactListItem[]>({
    queryKey: ["artifacts", workflowId, executionAttempt],
    queryFn: async () => {
      const params = executionAttempt != null ? `?execution_attempt=${executionAttempt}` : "";
      const res = await api.get(`/workflows/${workflowId}/artifacts${params}`);
      return res.data;
    },
    enabled: !!workflowId && enabled,
  });
}

export function useArtifact(artifactId: string | null) {
  return useQuery<ArtifactDetail>({
    queryKey: ["artifact", artifactId],
    queryFn: async () => {
      const res = await api.get(`/artifacts/${artifactId}`);
      return res.data;
    },
    enabled: !!artifactId,
  });
}
