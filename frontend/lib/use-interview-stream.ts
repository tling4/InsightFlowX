"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { InterviewSSEMessage } from "@/types/interview";

interface UseInterviewStreamOptions {
  workflowId: string;
  token: string;
}

export function useInterviewStream({ workflowId, token }: UseInterviewStreamOptions) {
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (
      userMessage: string,
      onToken: (token: string) => void,
      onConfig: (config: InterviewSSEMessage) => void,
      onComplete: () => void,
      onError: (err: Error) => void
    ) => {
      setIsStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/workflows/${workflowId}/interview/stream`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ user_message: userMessage }),
            signal: controller.signal,
          }
        );

        if (!res.ok) throw new Error(`Interview SSE failed: ${res.status}`);

        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let inMeta = false;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.includes("---META---")) {
              inMeta = true;
              continue;
            }

            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6);

            if (inMeta) {
              try {
                const parsed = JSON.parse(data) as InterviewSSEMessage;
                if (parsed.extracted_config || parsed.suggested_competitors) {
                  onConfig(parsed);
                }
                if (parsed.is_complete) {
                  onComplete();
                }
              } catch {
                // skip
              }
              continue;
            }

            if (data && data !== "[DONE]") {
              onToken(data);
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          onError(err as Error);
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [workflowId, token]
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { sendMessage, cancel, isStreaming };
}
