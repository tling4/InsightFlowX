import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle, ArrowRight } from "lucide-react";

interface Revision {
  number: number;
  passed: boolean;
  targetNode?: string;
  score?: number;
}

interface Props {
  revisions: Revision[];
}

export function RevisionTimeline({ revisions }: Props) {
  if (revisions.length === 0) return null;

  return (
    <div className="flex items-center gap-2 text-xs py-2 px-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border)]">
      <span className="text-[var(--text-muted)] font-medium">Revision History:</span>
      {revisions.map((rev, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <ArrowRight size={12} className="text-[var(--text-muted)]" />}
          <span className="flex items-center gap-1">
            <span className="text-[var(--text-primary)] font-mono">#{rev.number}</span>
            {rev.passed ? (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 size={10} /> Passed
              </Badge>
            ) : (
              <Badge variant="danger" className="gap-1">
                <XCircle size={10} /> Failed
              </Badge>
            )}
            {rev.score != null && (
              <span className="text-[var(--text-muted)] font-mono">{rev.score}%</span>
            )}
            {rev.targetNode && (
              <span className="text-amber-400">→ {rev.targetNode}</span>
            )}
          </span>
        </span>
      ))}
    </div>
  );
}
