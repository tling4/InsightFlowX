import * as React from "react";
import { cn } from "@/lib/cn";

const variants = {
  default: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200",
  primary: "bg-emerald-600 text-white hover:bg-emerald-500",
  destructive: "bg-rose-600 text-white hover:bg-rose-500",
  ghost: "bg-transparent hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)]",
  outline: "border border-[var(--border)] bg-transparent hover:bg-[var(--bg-elevated)] text-[var(--text-primary)]",
} as const;

const sizes = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-sm",
  icon: "h-9 w-9",
} as const;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

export function Button({
  className,
  variant = "default",
  size = "md",
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        variants[variant],
        sizes[size],
        className
      )}
      disabled={disabled}
      {...props}
    />
  );
}
