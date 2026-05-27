import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

interface SpinnerProps {
  className?: string;
  size?: number;
}

export function Spinner({ className, size = 16 }: SpinnerProps) {
  return <Loader2 className={cn("animate-spin text-emerald-400", className)} size={size} />;
}
