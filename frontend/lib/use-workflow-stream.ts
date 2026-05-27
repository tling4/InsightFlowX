"use client";

import { useEffect, useRef, useCallback } from "react";
import type { WorkflowEvent } from "@/types/event";

interface UseWorkflowStreamOptions {
  workflowId: string;
  token: string;
  enabled: boolean;
  onEvent: (event: WorkflowEvent) => void;
  onError?: (error: Event) => void;
}

export function useWorkflowStream({
  workflowId,
  token,
  enabled,
  onEvent,
  onError,
}: UseWorkflowStreamOptions) {
  const abortRef = useRef<AbortController | null>(null);
  const reconnectDelayRef = useRef(1000);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(async () => {
    if (!enabled) return;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
      const res = await fetch(`${baseUrl}/workflows/${workflowId}/stream`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`SSE failed: ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (!data) continue;
          try {
            const parsed = JSON.parse(data) as WorkflowEvent;
            reconnectDelayRef.current = 1000;
            onEvent(parsed);
          } catch {
            // skip
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onError?.(err as Event);
        reconnectTimerRef.current = setTimeout(() => {
          reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 30000);
          connect();
        }, reconnectDelayRef.current);
      }
    }
  }, [workflowId, token, enabled, onEvent, onError]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current != null) clearTimeout(reconnectTimerRef.current);
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { disconnect };
}
