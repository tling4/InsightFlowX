from enum import Enum
from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    CREATED = "created"
    CONFIGURING = "configuring"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProductCategory(str, Enum):
    SAAS = "SaaS / 协作工具"
    MOBILE_APP = "移动应用"
    HARDWARE = "硬件产品"


class WorkflowCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="工作流标题")


class WorkflowConfig(BaseModel):
    target_product: str = Field(..., description="目标分析产品名称")
    product_category: ProductCategory = Field(..., description="产品品类")
    focus_dimensions: list[str] = Field(default_factory=lambda: ["功能", "定价", "用户评价", "市场定位"], description="关注维度列表")
    competitor_count: int = Field(default=5, ge=1, le=10, description="最多分析竞品数量")
    competitors: list[str] = Field(default_factory=list, description="已确定的竞品名称列表")
    language: str = Field(default="zh", description="报告语言")
    extra_requirements: str = Field(default="", description="用户额外需求")


