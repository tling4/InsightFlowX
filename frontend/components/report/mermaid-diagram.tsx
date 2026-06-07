"use client";

import { useEffect, useId, useState } from "react";

interface Props {
  chart: string;
}

export function MermaidDiagram({ chart }: Props) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const elementId = useId().replace(/:/g, "");

  useEffect(() => {
    let active = true;

    async function renderChart() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "dark",
        });
        const { svg: rendered } = await mermaid.render(`mermaid-${elementId}`, chart.trim());
        if (!active) return;
        setSvg(rendered);
        setError(null);
      } catch (err) {
        if (!active) return;
        const message = err instanceof Error ? err.message : "流程图渲染失败";
        setError(message);
        setSvg("");
      }
    }

    if (chart.trim()) {
      void renderChart();
    }

    return () => {
      active = false;
    };
  }, [chart, elementId]);

  if (error) {
    return (
      <div className="my-4 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
        <p className="mb-2 text-sm font-medium text-amber-200">流程图渲染失败</p>
        <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-amber-50">{chart}</pre>
        <p className="mt-2 text-xs text-amber-200/80">{error}</p>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-4 text-sm text-[var(--text-muted)]">
        正在渲染流程图...
      </div>
    );
  }

  return (
    <div
      className="my-4 overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
