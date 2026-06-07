"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReportOutput } from "@/types/artifact";
import { MermaidDiagram } from "@/components/report/mermaid-diagram";

interface Props {
  report: ReportOutput;
  activeSection: string | null;
  onCitationClick: (index: number) => void;
}

export function ReportViewer({ report, activeSection, onCitationClick }: Props) {
  return (
    <div className="prose dark:prose-invert max-w-none leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const match = href?.match(/^#citation-(\d+)$/);
            if (match) {
              return (
                <button
                  onClick={() => onCitationClick(parseInt(match[1]))}
                  className="text-emerald-400 hover:underline cursor-pointer"
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
                {children}
              </a>
            );
          },
          h2: ({ children, className = "", ...props }) => {
            const id = typeof children === "string" ? children : "";
            const isActive = activeSection === id;
            return (
              <h2
                {...props}
                id={id}
                className={`scroll-mt-20 ${isActive ? "text-emerald-300" : ""} ${className}`}
              >
                {children}
              </h2>
            );
          },
          code: ({ className, children }) => {
            const value = String(children).replace(/\n$/, "");
            if (className?.includes("language-mermaid")) {
              return <MermaidDiagram chart={value} />;
            }
            return (
              <code className={className}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {report.full_markdown}
      </ReactMarkdown>
    </div>
  );
}
