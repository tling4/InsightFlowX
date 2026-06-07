"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Spinner } from "@/components/ui/spinner";
import type { InterviewMessage } from "@/types/interview";

interface Props {
  messages: InterviewMessage[];
  isStreaming: boolean;
  onQuickReply?: (text: string) => void;
}

export function ChatStream({ messages, isStreaming, onQuickReply }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const visibleMessages = messages.filter(
    (msg, index) => Boolean(msg.content) || (isStreaming && index === messages.length - 1),
  );

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-6">
      {visibleMessages.map((msg, i) => (
        <div key={i} className={`flex w-full ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
          <div
            className={`max-w-[75%] rounded-2xl px-5 py-4 text-sm leading-relaxed ${
              msg.role === "user"
                ? "bg-blue-600 text-white rounded-tr-md shadow-sm"
                : "bg-white dark:bg-zinc-900 border border-slate-100 dark:border-zinc-800 rounded-tl-md text-slate-800 dark:text-zinc-200 shadow-sm"
            }`}
          >
            {msg.content ? (
              msg.role === "user" ? (
                <p className="leading-relaxed">{msg.content}</p>
              ) : (
                <div className="
                  prose prose-sm max-w-none dark:prose-invert
                  prose-p:leading-[1.85] prose-p:my-3
                  prose-headings:font-semibold prose-headings:tracking-tight
                  prose-h2:text-base prose-h2:mt-6 prose-h2:mb-4
                  prose-h3:text-sm prose-h3:mt-5 prose-h3:mb-3
                  prose-strong:font-medium
                  prose-li:my-2 prose-li:leading-[1.85]
                  prose-ul:my-4 prose-ol:my-4
                  prose-ul:list-none prose-ul:pl-0
                  prose-ol:list-none prose-ol:pl-0
                  prose-code:text-emerald-300 dark:prose-code:bg-zinc-800 prose-code:bg-zinc-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:font-normal prose-code:text-xs
                  space-y-3
                ">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      li: ({ children }) => {
                        const text = extractText(children);
                        return (
                          <OptionCard
                            text={text}
                            onClick={() => onQuickReply?.(text)}
                          >
                            <div className="text-sm text-[var(--text-secondary)] leading-[1.85]">{children}</div>
                          </OptionCard>
                        );
                      },
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                </div>
              )
            ) : (
              isStreaming && i === visibleMessages.length - 1 && (
                <div className="flex items-center gap-2 text-zinc-500">
                  <Spinner size={14} />
                  <span className="text-xs">AI 正在思考...</span>
                </div>
              )
            )}
          </div>
        </div>
      ))}
      {visibleMessages.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full text-center gap-3">
          <div className="w-12 h-12 rounded-full bg-[var(--bg-elevated)] flex items-center justify-center">
            <svg className="w-6 h-6 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>
          <p className="text-sm text-[var(--text-secondary)] font-medium">开始对话</p>
          <p className="text-xs text-[var(--text-muted)]">AI 将通过对话引导你完成竞品分析配置</p>
        </div>
      )}
    </div>
  );
}

/* ─── Option Card ─── */
function OptionCard({
  text,
  onClick,
  children,
}: {
  text: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  const [selected, setSelected] = useState(false);

  const handleClick = () => {
    setSelected(true);
    onClick?.();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleClick(); }}
      className={`group w-full text-left p-4 rounded-xl border transition-all duration-200 mb-2 cursor-pointer
        ${selected
          ? "border-blue-500/40 bg-blue-500/5 ring-1 ring-blue-500/20"
          : "border-slate-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-900/50 hover:border-blue-500/30 hover:bg-blue-50/10 dark:hover:bg-blue-500/5 hover:-translate-y-0.5 active:scale-[0.99] shadow-sm"
        }`}
    >
      <div className="flex items-start gap-3">
        {selected && (
          <span className="mt-0.5 shrink-0 w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          </span>
        )}
        <div className="flex-1 min-w-0">
          {children}
        </div>
      </div>
    </div>
  );
}

/* ─── Helpers ─── */
function extractText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractText).join(" ");
  if (children && typeof children === "object" && "props" in children) {
    return extractText((children as { props: { children?: React.ReactNode } }).props.children);
  }
  return "";
}
