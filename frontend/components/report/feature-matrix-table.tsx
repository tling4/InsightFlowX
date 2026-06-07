import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { FeatureMatrix } from "@/types/artifact";

interface Props {
  data: FeatureMatrix;
}

export function FeatureMatrixTable({ data }: Props) {
  const visibleRows = data.matrix.filter((row) => {
    if (!row.comparisons?.length) return true;
    return row.comparisons.some(
      (comparison) => !["", "unknown", "未确认"].includes(comparison.support_level?.trim().toLowerCase() ?? "")
    );
  });
  const products = Object.keys(visibleRows[0]?.products ?? {});

  return (
    <Card>
      <CardHeader>
        <CardTitle>功能对比矩阵</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-4 text-[var(--text-muted)] font-medium">维度</th>
              {products.map((p) => (
                <th key={p} className="text-center py-2 px-4 text-[var(--text-primary)] font-medium">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => (
              <tr key={i} className="border-b border-[var(--border)] hover:bg-[var(--bg-elevated)]">
                <td className="py-2 px-4 text-[var(--text-secondary)]">{row.feature_name}</td>
                {products.map((p) => {
                  const val = row.products[p];
                  const lower = val?.toLowerCase?.() ?? "";
                  const isPositive =
                    lower === "true" || lower === "yes" || lower === "具备" || lower === "支持";
                  const isNegative = lower === "false" || lower === "no" || lower === "—";
                  return (
                    <td key={p} className="py-2 px-4 text-center">
                      {isPositive ? (
                        <Badge variant="success">具备</Badge>
                      ) : isNegative ? (
                        <span className="text-[var(--text-muted)]">—</span>
                      ) : (
                        <span className="text-xs text-[var(--text-secondary)]">{val || "—"}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
