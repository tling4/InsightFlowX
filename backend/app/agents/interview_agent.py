import json
import re
from typing import AsyncGenerator, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, BaseMessage
from app.config import get_settings
from app.schemas.workflow import WorkflowConfig, ProductCategory


# 不同产品类别的搜索模板，供前端展示或后续集成搜索 API 时使用。
# 当前 interview 阶段不执行实际搜索，仅收集配置。
SEARCH_TEMPLATES = {
    ProductCategory.SAAS: {
        "general": "{competitor} 功能对比 定价 用户评价 site:zhihu.com OR site:sspai.com",
        "pricing": "{competitor} 订阅价格 收费模式 版本对比",
        "reviews": "{competitor} 差评 吐槽 使用体验"
    },
    ProductCategory.MOBILE_APP: {
        "general": "{competitor} 功能 评分 用户评价 site:apps.apple.com OR site:coolapk.com",
        "pricing": "{competitor} 内购 会员 价格",
        "reviews": "{competitor} 用户吐槽 体验问题 优缺点"
    },
    ProductCategory.HARDWARE: {
        "general": "{competitor} 参数 价格 评测 site:zhihu.com OR site:smzdm.com",
        "pricing": "{competitor} 售价 首发价 历史价格",
        "reviews": "{competitor} 测评 拆机 优缺点"
    }
}


SYSTEM_PROMPT = """你是一个专业的竞品分析访谈助手，负责在正式启动多Agent分析之前，通过自然的多轮对话，引导用户明确以下信息：
1. 要做竞品分析的目标产品是什么
2. 产品属于哪一类（SaaS / 协作工具、移动应用、硬件产品）
3. 你希望重点关注哪些分析维度
4. 最多需要对比多少个竞品
5. 你有没有其他额外的分析要求

规则：
- 不要一次把所有问题全部抛给用户，用非常自然的对话引导用户逐步说明
- 当信息收集完整后，用清晰的结构化卡片形式展示你理解到的配置，请求用户确认
- 确认后输出完整的WorkflowConfig JSON，格式必须符合规范
- 同时给出 product_profile，用于描述目标产品画像和竞品选择边界；如果不确定，字段留空或给出保守判断
- competitors 只放真正的主竞品，不要放同品牌同系列配置变体、配件、媒体网站、论坛标题或用户自然语言片段
- 所有输出语言保持中文
- 不要做任何无关闲聊，始终围绕竞品分析需求展开
- 输出的JSON包裹在```json代码块中，用于系统自动提取配置，不会展示给用户
- 输出的JSON必须严格是以下Schema，不要额外字段：
{
  "target_product": "字符串，目标产品名称",
  "product_category": "字符串，必须是三个选项之一：SaaS / 协作工具、移动应用、硬件产品",
  "product_profile": {
    "canonical_name": "字符串，目标产品规范名称",
    "product_form": "字符串，产品形态，例如 hardware/software/service/platform",
    "market_category": "字符串，细分市场，例如 smartphone、AI coding assistant、EV、cloud database",
    "brand": "字符串，品牌或厂商",
    "product_line": "字符串，产品线或系列",
    "model": "字符串，型号",
    "variant_tier": "字符串，SKU层级，例如 standard、pro、ultra、plus、max；标准款填 standard",
    "market_segment": "字符串，市场定位或价位段",
    "competition_basis": "字符串数组，竞品必须满足的边界",
    "exclude_relations": "字符串数组，必须排除的候选关系"
  },
  "focus_dimensions": "字符串数组，用户指定的关注维度",
  "competitor_count": "整数，1-10之间",
  "competitors": "字符串数组，确定的竞品名称列表",
  "language": "zh",
  "extra_requirements": "字符串"
}

当配置确认完全无误后，在回复末尾单独一行输出 ---CONFIG_COMPLETE---"""


class InterviewAgent:
    """访谈 Agent：多轮对话引导用户明确竞品分析配置。

    独立于 DAG 工作流之外，在工作流创建前运行。
    通过 SSE 流式输出对话内容，最终解析 WorkflowConfig 用于创建正式工作流。

    与 DAG 内 agent 的区别：
    - 不继承 BaseAgent（不参与 LangGraph 编排，无 node_name）
    - 直接管理自己的 ChatOpenAI 实例（streaming=True，用于对话场景）
    - 使用 ---CONFIG_COMPLETE--- 哨兵标记对话结束，而非结构化输出解析
    """

    def __init__(self):
        settings = get_settings()
        self.llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            streaming=True
        )
        self.system_message = SystemMessage(content=SYSTEM_PROMPT)

    async def stream_response(self, history_messages: List[BaseMessage]) -> AsyncGenerator[str, None]:
        """流式生成访谈回复，逐 token yield 供 SSE 推向前端。"""
        full_content = ""
        async for chunk in self.llm.astream([self.system_message] + history_messages):
            content = chunk.content
            if isinstance(content, list):
                content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
            if content:
                full_content += content
                yield content

    def try_extract_config(self, full_text: str) -> WorkflowConfig | None:
        """从 LLM 累积回复中提取 WorkflowConfig。

        策略：(1) 优先剥离 markdown 代码围栏 ```json ... ``` 内的内容；
        (2) 否则用平衡括号扫描器在全文中找出所有顶层 JSON object，
            依次尝试解析与 Pydantic 校验，返回**最后一个**通过校验的 object。

        相比旧的 find/rfind 匹配，平衡扫描可避免吞并对话文本中的 `{user_name}` 等
        碎片大括号；优先取最后一个有效 block 是因为 LLM 通常会先草拟再给出最终配置。
        """
        fence_matches = re.findall(r'```(?:json)?\s*\n?(.*?)\n?```', full_text, re.DOTALL)
        for match in fence_matches:
            config = self._parse_json_block(match)
            if config:
                return config
        last_valid: WorkflowConfig | None = None
        for block in self._iter_balanced_json_blocks(full_text):
            parsed = self._parse_json_block(block)
            if parsed:
                last_valid = parsed
        return last_valid

    def _iter_balanced_json_blocks(self, text: str):
        """从 text 中以平衡括号扫描方式 yield 每个顶层 `{...}` 子串。

        正确处理字符串字面量中的大括号与 `\\"` 转义，避免对话文本里的 `{x}`
        与真正 JSON 混淆。
        """
        depth = 0
        start = -1
        in_string = False
        escape = False
        for i, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        yield text[start:i + 1]
                        start = -1

    def _parse_json_block(self, text: str) -> WorkflowConfig | None:
        try:
            stripped = text.strip()
            if not stripped.startswith("{"):
                # 兼容上层传入的完整 markdown 段；fallback 到首尾大括号
                start = stripped.find("{")
                end = stripped.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    return None
                stripped = stripped[start:end + 1]
            data = json.loads(stripped)
            return WorkflowConfig(**data)
        except Exception:
            return None

    def is_complete_signal(self, full_text: str) -> bool:
        """检测 LLM 是否输出了配置完成哨兵。

        哨兵机制比 try_extract_config 更可靠：LLM 可能提前输出类似 JSON 的文本
        但实际尚未完成信息收集，哨兵保证配置是 LLM 确认后的最终版本。
        """
        return "---CONFIG_COMPLETE---" in full_text
