"use client";

import Link from "next/link";
import { RegisterForm } from "@/components/auth/register-form";

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-xl font-bold text-[var(--text-primary)]">创建账号</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">注册 DAGents InsightFlow</p>
        </div>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
          <RegisterForm />
        </div>
        <p className="text-center text-xs text-[var(--text-muted)]">
          已有账号？{" "}
          <Link href="/auth/login" className="text-emerald-500 hover:underline font-medium">
            登录
          </Link>
        </p>
      </div>
    </div>
  );
}
