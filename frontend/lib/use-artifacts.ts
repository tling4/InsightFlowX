"use client";

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import type { ArtifactListItem, ArtifactDetail } from "@/types/artifact";

export function useArtifacts(workflowId: string, enabled = true) {
  return useQuery<ArtifactListItem[]>({
    queryKey: ["artifacts", workflowId],
    queryFn: async () => {
      const res = await api.get(`/workflows/${workflowId}/artifacts`);
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
