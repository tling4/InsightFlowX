from enum import Enum
from pydantic import BaseModel, Field


class DecisionAction(str, Enum):
    JUMP = "jump"
    APPROVE = "approve"
    ABORT = "abort"
    DROP_COMPETITOR = "drop_competitor"
    KEEP_WITH_INSUFFICIENT_EVIDENCE = "keep_with_insufficient_evidence"
    REPLACE_COMPETITOR = "replace_competitor"


class DecisionRequest(BaseModel):
    action: DecisionAction
    target_node: str | None = Field(
        default=None,
        description="jump 时指定跳转目标节点。为空时 fallback 到 agent 建议的 target_node",
    )
    feedback: str = Field(default="", description="人工反馈信息")
    competitor: str | None = Field(default=None, description="需要移除/保留/替换的竞品名称；为空时默认使用受影响对象")
    replacement_competitor: str | None = Field(default=None, description="替换后的竞品名称，仅 replace_competitor 使用")
