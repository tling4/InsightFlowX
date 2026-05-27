"use client";

import Link from "next/link";
import { LoginForm } from "@/components/auth/login-form";
import { Sparkles } from "lucide-react";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mx-auto mb-4">
            <Sparkles size={22} className="text-emerald-400" />
          </div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">DAGents InsightFlow</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">AI-Native Workflow Observatory</p>
        </div>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-6">
          <LoginForm />
        </div>
        <p className="text-center text-xs text-[var(--text-muted)]">
          还没有账号？{" "}
          <Link href="/auth/register" className="text-emerald-500 hover:underline font-medium">
            注册
          </Link>
        </p>
      </div>
    </div>
  );
}
