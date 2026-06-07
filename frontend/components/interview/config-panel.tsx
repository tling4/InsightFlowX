"use client";

import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Plus, X, ChevronDown, Pencil } from "lucide-react";
import { useState } from "react";
import type { CompetitorGroups, ProductCategory, ProductProfile, WorkflowConfig } from "@/types/workflow";

interface Props {
  config: Partial<WorkflowConfig>;
  isComplete: boolean;
  isStarting: boolean;
  newCompetitor: string;
  /** 本地校验：target_product + product_category 是否都已填写 */
  canStart: boolean;
  /** 后端 /start 失败信息（如 ConfigIncompleteError 等），非 null 时高亮显示 */
  startError: string | null;
  onNewCompetitorChange: (v: string) => void;
  onAddCompetitor: () => void;
  onRemoveCompetitor: (name: string) => void;
  onConfigChange: (field: string, value: unknown) => void;
  onStart: () => void;
  /** 解锁访谈对话（isComplete 翻回 false），用于配置不满意时继续修订 */
  onResumeEditing: () => void;
}

export function ConfigPanel({
  config,
  isComplete,
  isStarting,
  newCompetitor,
  canStart,
  startError,
  onNewCompetitorChange,
  onAddCompetitor,
  onRemoveCompetitor,
  onConfigChange,
  onStart,
  onResumeEditing,
}: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setCollapsed((p) => ({ ...p, [k]: !p[k] }));
  const productProfile = config.product_profile ?? emptyProductProfile(config);
  const competitorGroups = config.competitor_groups ?? emptyCompetitorGroups();
  const updateProfile = (field: keyof ProductProfile, value: string | string[]) => {
    onConfigChange("product_profile", {
      ...productProfile,
      [field]: value,
    });
  };
  const updateCompetitorGroup = (field: keyof CompetitorGroups, value: string[]) => {
    onConfigChange("competitor_groups", {
      ...competitorGroups,
      [field]: value,
    });
  };

  return (
    <div className="flex flex-col h-full space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
            实时配置看板
            {!isComplete && (
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="w-1 h-1 rounded-full bg-emerald-400"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1, delay: i * 0.2, repeat: Infinity }}
                  />
                ))}
              </span>
            )}
          </h2>
          <p className="text-xs text-[var(--text-muted)]">AI 从对话中提取的结构化配置</p>
        </div>
        {isComplete && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="shrink-0 w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center"
          >
            <Check size={12} className="text-emerald-400" />
          </motion.span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]/60 backdrop-blur-xl p-4">
        <FieldSection label="分析标题" collapsed={collapsed.title} onToggle={() => toggle("title")}>
          <Input
            value={typeof config.target_product === "string" ? config.target_product : ""}
            onChange={(e) => onConfigChange("target_product", e.target.value)}
            placeholder="等待 AI 提取..."
            className="h-9 text-sm bg-[var(--bg-elevated)] border-[var(--border)]"
          />
        </FieldSection>

        <FieldSection label="产品品类" collapsed={collapsed.category} onToggle={() => toggle("category")}>
          <div className="flex gap-1.5 flex-wrap">
            {(PRODUCT_CATEGORIES as readonly ProductCategory[]).map((cat) => (
              <button
                key={cat}
                onClick={() => onConfigChange("product_category", cat)}
                className={`px-3 py-1.5 rounded-lg text-xs border transition-all ${
                  config.product_category === cat
                    ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                    : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--text-secondary)]"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </FieldSection>

        <FieldSection label="产品画像" collapsed={collapsed.profile} onToggle={() => toggle("profile")}>
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <ProfileInput
                label="规范名称"
                value={productProfile.canonical_name}
                placeholder={config.target_product || "等待识别..."}
                onChange={(value) => updateProfile("canonical_name", value)}
              />
              <ProfileInput
                label="产品形态"
                value={productProfile.product_form}
                placeholder="hardware / software"
                onChange={(value) => updateProfile("product_form", value)}
              />
              <ProfileInput
                label="细分市场"
                value={productProfile.market_category}
                placeholder="smartphone"
                onChange={(value) => updateProfile("market_category", value)}
              />
              <ProfileInput
                label="市场定位"
                value={productProfile.market_segment}
                placeholder="flagship smartphone"
                onChange={(value) => updateProfile("market_segment", value)}
              />
              <ProfileInput
                label="品牌"
                value={productProfile.brand}
                placeholder="Samsung"
                onChange={(value) => updateProfile("brand", value)}
              />
              <ProfileInput
                label="产品线"
                value={productProfile.product_line}
                placeholder="Galaxy S"
                onChange={(value) => updateProfile("product_line", value)}
              />
              <ProfileInput
                label="SKU层级"
                value={productProfile.variant_tier}
                placeholder="standard / pro / ultra"
                onChange={(value) => updateProfile("variant_tier", value)}
              />
            </div>
            <ProfileInput
              label="型号"
              value={productProfile.model}
              placeholder="S26"
              onChange={(value) => updateProfile("model", value)}
            />
            <ListProfileInput
              label="竞品边界"
              value={productProfile.competition_basis}
              placeholder="same category, similar price band"
              onChange={(value) => updateProfile("competition_basis", value)}
            />
            <ListProfileInput
              label="排除关系"
              value={productProfile.exclude_relations}
              placeholder="same brand same series variant, accessory"
              onChange={(value) => updateProfile("exclude_relations", value)}
            />
          </div>
        </FieldSection>

        <FieldSection label="竞品与角色判断" collapsed={collapsed.competitors} onToggle={() => toggle("competitors")}>
          <p className="text-[11px] text-[var(--text-muted)] mb-2">
            这里优先展示你明确要分析的竞品；五类角色只是参考标签，不需要凑满才能开始分析。
          </p>
          <div className="space-y-2">
            <GroupedCompetitorInput
              label="核心竞品"
              description="与我们高度重合，必须深挖"
              value={competitorGroups.core}
              placeholder="如：Notion"
              onChange={(value) => updateCompetitorGroup("core", value)}
            />
            <GroupedCompetitorInput
              label="标杆竞品"
              description="更强更大，适合学习方向"
              value={competitorGroups.benchmark}
              placeholder="如：Confluence"
              onChange={(value) => updateCompetitorGroup("benchmark", value)}
            />
            <GroupedCompetitorInput
              label="潜力竞品"
              description="规模未必大，但打法有亮点"
              value={competitorGroups.potential}
              placeholder="如：ClickUp"
              onChange={(value) => updateCompetitorGroup("potential", value)}
            />
            <GroupedCompetitorInput
              label="替代竞品"
              description="形态不同，但解决同一需求"
              value={competitorGroups.substitute}
              placeholder="如：Airtable"
              onChange={(value) => updateCompetitorGroup("substitute", value)}
            />
            <GroupedCompetitorInput
              label="避坑竞品"
              description="反面教材，帮助明确不做什么"
              value={competitorGroups.pitfall}
              placeholder="如：某失败案例产品"
              onChange={(value) => updateCompetitorGroup("pitfall", value)}
            />
          </div>
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            <div className="text-[10px] text-[var(--text-muted)] mb-2">竞品总表</div>
            <div className="flex flex-wrap gap-1.5">
              {(config.competitors ?? []).map((c) => (
                <Badge key={c} className="gap-1 bg-[var(--bg-elevated)] text-[var(--text-secondary)] border-[var(--border)]">
                  {c}
                  <X className="h-3 w-3 cursor-pointer hover:text-rose-400" onClick={() => onRemoveCompetitor(c)} />
                </Badge>
              ))}
              {(!config.competitors || config.competitors.length === 0) && (
                <span className="text-xs text-[var(--text-muted)] italic">先通过访谈确认你真正想分析的竞品...</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
          </div>
          <div className="flex gap-1.5 mt-2">
            <Input value={newCompetitor} onChange={(e) => onNewCompetitorChange(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAddCompetitor()}
              placeholder="补充要分析的竞品" className="h-8 text-xs bg-[var(--bg-elevated)] border-[var(--border)]"
            />
            <Button size="sm" variant="ghost" onClick={onAddCompetitor}><Plus size={12} /></Button>
          </div>
        </FieldSection>

        <FieldSection label="系统分析框架" collapsed={collapsed.dimensions} onToggle={() => toggle("dimensions")}>
          <p className="text-[11px] text-[var(--text-muted)] mb-2">
            这里的维度由系统根据你的问题自动推断，不再要求你手动指定。
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(config.focus_dimensions ?? []).map((d) => (
              <Badge key={d} variant="success">{d}</Badge>
            ))}
            {(!config.focus_dimensions || config.focus_dimensions.length === 0) && (
              <span className="text-xs text-[var(--text-muted)] italic">系统将自动补齐默认分析框架...</span>
            )}
          </div>
        </FieldSection>
      </div>

      {/* /start 错误内联回显 */}
      {startError && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {startError}
        </div>
      )}

      <AnimatePresence>
        {/* 显示 Start 按钮的条件：LLM 已发出完成哨兵，或本地校验已通过（允许无 sentinel 也能启动） */}
        {(isComplete || canStart) && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="space-y-2"
          >
            <Button
              onClick={onStart}
              disabled={isStarting || !canStart}
              className="w-full py-5 text-sm font-semibold rounded-2xl bg-emerald-500 hover:bg-emerald-600 text-white shadow-[0_0_24px_var(--accent-glow)] transition-all duration-300 hover:shadow-[0_0_36px_var(--accent-glow)] disabled:bg-zinc-700 disabled:shadow-none disabled:cursor-not-allowed"
            >
              {isStarting ? (
                <span className="flex items-center gap-2"><Spinner size={14} /> 启动 LangGraph 引擎...</span>
              ) : (
                <span className="flex items-center gap-2"><Check size={16} /> 确认配置并启动分析</span>
              )}
            </Button>
            {!canStart && (
              <p className="text-[11px] text-amber-400/80 text-center">
                请先补全产品名称和品类
              </p>
            )}
            {isComplete && (
              <Button
                variant="ghost"
                onClick={onResumeEditing}
                className="w-full h-8 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <Pencil size={12} className="mr-1" /> 继续编辑访谈
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function emptyProductProfile(config: Partial<WorkflowConfig>): ProductProfile {
  return {
    canonical_name: config.target_product ?? "",
    product_form: "",
    market_category: "",
    brand: "",
    product_line: "",
    model: "",
    variant_tier: "",
    market_segment: "",
    competition_basis: [],
    exclude_relations: [],
  };
}

function emptyCompetitorGroups(): CompetitorGroups {
  return {
    core: [],
    benchmark: [],
    potential: [],
    substitute: [],
    pitfall: [],
  };
}

const PRODUCT_CATEGORIES = [
  "企业软件 / SaaS",
  "AI 产品 / 智能助手",
  "移动应用",
  "硬件 / 消费电子",
  "平台 / 社区 / 内容",
  "电商 / 零售 / 本地生活",
] as const;

function ProfileInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value?: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="block text-[10px] text-[var(--text-muted)]">{label}</span>
      <Input
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-8 text-xs bg-[var(--bg-elevated)] border-[var(--border)]"
      />
    </label>
  );
}

function ListProfileInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value?: string[];
  placeholder?: string;
  onChange: (value: string[]) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="block text-[10px] text-[var(--text-muted)]">{label}</span>
      <Input
        value={(value ?? []).join(", ")}
        onChange={(e) => onChange(splitProfileList(e.target.value))}
        placeholder={placeholder}
        className="h-8 text-xs bg-[var(--bg-elevated)] border-[var(--border)]"
      />
    </label>
  );
}

function GroupedCompetitorInput({
  label,
  description,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  description: string;
  value?: string[];
  placeholder?: string;
  onChange: (value: string[]) => void;
}) {
  return (
    <label className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="block text-[10px] text-[var(--text-muted)]">{label}</span>
        <span className="text-[10px] text-[var(--text-muted)]">{description}</span>
      </div>
      <Input
        value={(value ?? []).join(", ")}
        onChange={(e) => onChange(splitProfileList(e.target.value))}
        placeholder={placeholder}
        className="h-8 text-xs bg-[var(--bg-elevated)] border-[var(--border)]"
      />
    </label>
  );
}

function splitProfileList(value: string): string[] {
  return value
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function FieldSection({
  label,
  children,
  collapsed,
  onToggle,
}: {
  label: string;
  children: React.ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  return (
    <div>
      <button onClick={onToggle} className="flex items-center gap-1 mb-1.5 w-full text-left group">
        <ChevronDown
          size={10}
          className={`text-[var(--text-muted)] transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        <p className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider font-medium">{label}</p>
      </button>
      {!collapsed && children}
    </div>
  );
}
