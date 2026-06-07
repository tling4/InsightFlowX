from enum import Enum
from pydantic import BaseModel, Field, model_validator


class WorkflowStatus(str, Enum):
    CREATED = "created"
    CONFIGURING = "configuring"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class ProductCategory(str, Enum):
    ENTERPRISE_SAAS = "企业软件 / SaaS"
    AI_PRODUCT = "AI 产品 / 智能助手"
    MOBILE_APP = "移动应用"
    HARDWARE = "硬件 / 消费电子"
    PLATFORM_CONTENT = "平台 / 社区 / 内容"
    ECOMMERCE_LOCAL = "电商 / 零售 / 本地生活"
    LEGACY_SAAS = "SaaS / 协作工具"
    LEGACY_HARDWARE = "硬件产品"


class WorkflowCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="工作流标题")


class WorkflowUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="工作流标题")


class ProductProfile(BaseModel):
    canonical_name: str = Field(default="", description="目标产品规范名称")
    product_form: str = Field(default="", description="产品形态，例如 hardware/software/service/platform")
    market_category: str = Field(default="", description="细分市场类别，例如 smartphone、AI coding assistant")
    brand: str = Field(default="", description="品牌或厂商")
    product_line: str = Field(default="", description="产品线或系列")
    model: str = Field(default="", description="型号")
    variant_tier: str = Field(default="", description="SKU 层级，例如 standard/pro/ultra/plus/max")
    market_segment: str = Field(default="", description="市场定位或价位段")
    competition_basis: list[str] = Field(default_factory=list, description="选择竞品时应满足的边界")
    exclude_relations: list[str] = Field(default_factory=list, description="需要排除的候选关系")


class CompetitorGroups(BaseModel):
    core: list[str] = Field(default_factory=list, description="核心竞品")
    benchmark: list[str] = Field(default_factory=list, description="标杆竞品")
    potential: list[str] = Field(default_factory=list, description="潜力竞品")
    substitute: list[str] = Field(default_factory=list, description="替代竞品")
    pitfall: list[str] = Field(default_factory=list, description="避坑竞品")


DEFAULT_FOCUS_DIMENSIONS = [
    "目标用户",
    "使用场景",
    "核心问题",
    "解决方案",
    "支撑点",
    "功能体验",
    "用户反馈",
    "上市与增长",
]

GROUP_FIELD_ORDER = ["core", "benchmark", "potential", "substitute", "pitfall"]


def dedupe_competitor_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in names:
        name = " ".join(str(raw).split()).strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(name)
    return result


def flatten_competitor_groups(groups: CompetitorGroups | dict | None) -> list[str]:
    if not groups:
        return []
    data = groups.model_dump() if isinstance(groups, CompetitorGroups) else groups
    merged: list[str] = []
    for field in GROUP_FIELD_ORDER:
        values = data.get(field, []) if isinstance(data, dict) else []
        if isinstance(values, list):
            merged.extend(values)
    return dedupe_competitor_names(merged)


def assign_competitor_groups(
    competitors: list[str],
    existing: CompetitorGroups | dict | None = None,
) -> CompetitorGroups:
    groups = existing if isinstance(existing, CompetitorGroups) else CompetitorGroups(**(existing or {}))
    normalized = {field: dedupe_competitor_names(getattr(groups, field)) for field in GROUP_FIELD_ORDER}
    assigned = set(name.lower() for name in flatten_competitor_groups(groups))
    for name in dedupe_competitor_names(competitors):
        lowered = name.lower()
        if lowered in assigned:
            continue
        placed = False
        for field in GROUP_FIELD_ORDER:
            if not normalized[field]:
                normalized[field].append(name)
                placed = True
                break
        if not placed:
            normalized["core"].append(name)
        assigned.add(lowered)
    return CompetitorGroups(**normalized)


def remove_competitors_from_groups(
    groups: CompetitorGroups | dict | None,
    competitors_to_remove: list[str],
) -> CompetitorGroups:
    normalized_groups = groups if isinstance(groups, CompetitorGroups) else CompetitorGroups(**(groups or {}))
    removals = {name.lower() for name in dedupe_competitor_names(competitors_to_remove)}
    if not removals:
        return normalized_groups
    cleaned = {}
    for field in GROUP_FIELD_ORDER:
        values = getattr(normalized_groups, field)
        cleaned[field] = [value for value in values if value.lower() not in removals]
    return CompetitorGroups(**cleaned)


class WorkflowConfig(BaseModel):
    target_product: str = Field(..., description="目标分析产品名称")
    product_category: ProductCategory = Field(..., description="产品品类")
    product_profile: ProductProfile | None = Field(default=None, description="系统识别出的可编辑产品画像")
    focus_dimensions: list[str] = Field(default_factory=lambda: list(DEFAULT_FOCUS_DIMENSIONS), description="系统推断的默认分析维度")
    competitor_count: int = Field(default=1, ge=1, le=10, description="本次分析的竞品数量")
    competitor_groups: CompetitorGroups = Field(default_factory=CompetitorGroups, description="按角色分类的竞品列表")
    competitors: list[str] = Field(default_factory=list, description="已确定的竞品名称列表")
    insufficient_evidence_competitors: list[str] = Field(default_factory=list, description="允许证据不足但继续分析的竞品")
    language: str = Field(default="zh", description="报告语言")
    extra_requirements: str = Field(default="", description="用户额外需求")

    @model_validator(mode="after")
    def sync_competitor_fields(self):
        self.focus_dimensions = dedupe_competitor_names(self.focus_dimensions) or list(DEFAULT_FOCUS_DIMENSIONS)
        grouped = flatten_competitor_groups(self.competitor_groups)
        flat = dedupe_competitor_names(self.competitors)
        self.insufficient_evidence_competitors = dedupe_competitor_names(self.insufficient_evidence_competitors)
        if grouped and flat:
            merged = dedupe_competitor_names(grouped + flat)
            self.competitor_groups = assign_competitor_groups(merged, self.competitor_groups)
            self.competitors = dedupe_competitor_names(flatten_competitor_groups(self.competitor_groups))
        elif grouped:
            self.competitors = grouped
        elif flat:
            self.competitor_groups = assign_competitor_groups(flat, self.competitor_groups)
            self.competitors = dedupe_competitor_names(flatten_competitor_groups(self.competitor_groups))
        self.competitor_count = max(1, len(self.competitors)) if self.competitors else 1
        return self
