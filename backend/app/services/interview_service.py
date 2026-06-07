import asyncio
import json
import logging
import uuid
from typing import List, AsyncGenerator, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from tavily import AsyncTavilyClient
from app.config import get_settings
from app.db.models.workflow import InterviewMessageModel
from app.db.queries.workflow_queries import get_workflow_by_uuid, get_message_history
from app.agents.interview_agent import InterviewAgent
from app.agents.competitor_resolver import resolve_competitors
from app.agents.product_profiler import build_product_profile
from app.schemas.workflow import ProductProfile, assign_competitor_groups, dedupe_competitor_names

settings = get_settings()
logger = logging.getLogger(__name__)

INTERVIEW_RESPONSE_TIMEOUT_SECONDS = 120
EMPTY_RESPONSE_FALLBACK = "刚才没有生成有效回复。请重新发送一次，或补充说明您希望继续确认的内容。"

_tavily_client: AsyncTavilyClient | None = None
_interview_agent: InterviewAgent | None = None


def _get_tavily_client() -> AsyncTavilyClient:
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
    return _tavily_client


def _get_interview_agent() -> InterviewAgent:
    global _interview_agent
    if _interview_agent is None:
        _interview_agent = InterviewAgent()
    return _interview_agent


def convert_to_langchain_messages(history: List[InterviewMessageModel]) -> List[BaseMessage]:
    """将 ORM 消息记录转为 LangChain BaseMessage 列表供 InterviewAgent 使用。"""
    messages: List[BaseMessage] = []
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))
    return messages


async def save_message(db: AsyncSession, workflow_id: uuid.UUID, role: str, content: str):
    """持久化一条访谈消息。"""
    message = InterviewMessageModel(
        workflow_id=workflow_id,
        role=role,
        content=content
    )
    db.add(message)
    await db.commit()


def _looks_like_user_confirmation(text: str) -> bool:
    normalized = "".join(str(text).strip().split()).lower()
    if not normalized:
        return False
    confirmation_markers = [
        "确认",
        "可以开始",
        "开始分析",
        "就按这个来",
        "按这个来",
        "没问题",
        "可以的",
        "好的开始",
        "开始吧",
        "ok",
        "okay",
        "yes",
    ]
    revision_markers = [
        "但是",
        "不过",
        "再改",
        "修改",
        "调整",
        "补充",
        "重新",
        "不对",
        "不太对",
        "先别",
        "等等",
    ]
    return any(marker in normalized for marker in confirmation_markers) and not any(
        marker in normalized for marker in revision_markers
    )


def _should_mark_complete(full_response: str, history: List[InterviewMessageModel], user_message: str) -> bool:
    if "---CONFIG_COMPLETE---" not in full_response:
        return False
    user_turns = sum(1 for msg in history if msg.role == "user")
    if user_turns < 2:
        return False
    return _looks_like_user_confirmation(user_message)


async def suggest_competitors(
    target_product: str,
    category: str,
    focus_dimensions: list[str] | None = None,
    existing_competitors: list[str] | None = None,
    competitor_count: int = 5,
    product_profile: ProductProfile | dict | None = None,
) -> List[str]:
    """通过 Tavily 搜索推荐并校验竞品列表。

    用户明确给出的竞品仍需经过相关性校验，避免把文章标题、功能描述或
    不同品类产品直接带入后续分析。
    """
    resolution = await resolve_competitors(
        client=_get_tavily_client(),
        target_product=target_product,
        category=category,
        focus_dimensions=focus_dimensions or [],
        competitor_names=existing_competitors or [],
        competitor_count=competitor_count,
        product_profile=product_profile,
    )
    if resolution.competitors:
        return resolution.competitors
    if existing_competitors:
        return dedupe_competitor_names(existing_competitors)
    # Fallback for categories not covered by deterministic extractors.
    try:
        query = f"与{target_product}同类的主流竞品产品有哪些，只返回产品名称列表，不返回其他内容"
        result = await _get_tavily_client().search(query, max_results=3)
        competitors = []
        for res in result.get("results", []):
            for text in [res.get("title", ""), res.get("content", "")]:
                for line in text.replace("、", "\n").replace("，", "\n").replace("。", "\n").split("\n"):
                    name = line.strip().strip("[]()（）【】\"'")
                    if name and name != target_product and len(name) < 30 and name not in competitors:
                        competitors.append(name)
        return dedupe_competitor_names(competitors)[:5]
    except Exception:
        return []


def merge_competitor_groups(config, suggested: list[str]) -> None:
    """将推荐竞品补齐到五类竞品槽位中，保留已有分类结果。"""
    config.competitor_groups = assign_competitor_groups(suggested, config.competitor_groups)
    config.competitors = config.competitors  # 触发后续 model_dump 前的字段读取一致性


async def _collect_interview_response(
    messages: List[BaseMessage],
    agent_factory: Callable[[], InterviewAgent] = _get_interview_agent,
) -> str:
    """Collect an interview reply, retrying once when the provider returns no text."""
    for attempt in range(2):
        chunks: list[str] = []
        async with asyncio.timeout(INTERVIEW_RESPONSE_TIMEOUT_SECONDS):
            async for chunk in agent_factory().stream_response(messages):
                chunks.append(chunk)
        response = "".join(chunks)
        if response.strip():
            return response
        logger.warning("Interview LLM returned an empty response (attempt %s/2)", attempt + 1)
    return EMPTY_RESPONSE_FALLBACK


async def stream_interview_response(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    user_message: str
) -> AsyncGenerator[str, None]:
    """处理用户消息 → 保存 → 请求 LLM → 积攒 → 提取配置 → 清洗 → 回放 → META。

    流程说明：
    - Phase A: 积攒 LLM 全部输出，不立即 yield（避免前端看到原始 WorkflowConfig JSON）
    - Phase B: 从原始文本提取配置，补全 product_profile / competitors
    - Phase C: 剥离 JSON 代码块，只保留对话文本
    - Phase D: 持久化清洗后的消息
    - Phase E: 以小块回放清洗文本（模拟流式效果）
    - Phase F: 推送 ---META--- 分隔行 + 最终配置 JSON

    META 包含：
      - is_complete: 是否已完成访谈
      - extracted_config: 经 suggest_competitors 处理后的最终配置
      - suggested_competitors: 与 extracted_config.competitors 一致
    """
    # -- Phase A: 积攒 -------------------------------------------------------
    await save_message(db, workflow_id, "user", user_message)
    history = await get_message_history(db, workflow_id)
    lc_messages = convert_to_langchain_messages(history)

    full_response = await _collect_interview_response(lc_messages)

    # -- Phase B: 提取 & 补全 config ----------------------------------------
    config = _get_interview_agent().try_extract_config(full_response)
    is_complete = _should_mark_complete(full_response, history, user_message)

    if config:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if workflow:
            config.product_profile = await build_product_profile(
                target_product=config.target_product,
                category=config.product_category,
                focus_dimensions=config.focus_dimensions,
                existing_profile=config.product_profile,
                client=_get_tavily_client(),
            )
            config.competitors = await suggest_competitors(
                config.target_product,
                config.product_category,
                config.focus_dimensions,
                config.competitors,
                config.competitor_count,
                config.product_profile,
            )
            merge_competitor_groups(config, config.competitors)
            workflow.config = config.model_dump()
            await db.commit()

    # -- Phase C: 清洗 -------------------------------------------------------
    # 取第一个 ``` 之前的文本作为聊天内容（丢弃 JSON 代码块和 ---CONFIG_COMPLETE---）
    cleaned_response = full_response.split("```", 1)[0].strip()

    # -- Phase D: 持久化清洗后的消息 ------------------------------------------
    await save_message(db, workflow_id, "assistant", cleaned_response)

    # -- Phase E: 回放 -------------------------------------------------------
    # 以 3 字符为粒度 yield，视觉上仍有打字效果
    chunk_len = 3
    for i in range(0, len(cleaned_response), chunk_len):
        yield cleaned_response[i:i + chunk_len]

    # -- Phase F: META --------------------------------------------------------
    yield "\n---META---\n"
    meta = {
        "is_complete": is_complete,
        "extracted_config": config.model_dump() if config else None,
        "suggested_competitors": config.competitors if config else [],
        "suggested_competitor_groups": config.competitor_groups.model_dump() if config else None,
    }
    yield json.dumps(meta, ensure_ascii=False)
