import json
import re
from typing import Any, Awaitable, Callable, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import get_settings

try:
    from langsmith import traceable
except ImportError:  # langsmith 未安装时不报错
    def traceable(**kwargs):  # type: ignore[no-redef]
        return lambda fn: fn


T = TypeVar("T", bound=BaseModel)

StreamCallback = Callable[[str], Awaitable[None]]


def has_real_value(value: str | None) -> bool:
    """检查配置值是否已填写真实内容，而非占位符或空值。"""
    if not value:
        return False
    lowered = value.strip().lower()
    return lowered not in {"", "local-dev-placeholder", "placeholder", "change-me-in-production"}


def llm_is_configured() -> bool:
    settings = get_settings()
    return has_real_value(settings.LLM_API_KEY) and has_real_value(settings.LLM_MODEL)


def tavily_is_configured() -> bool:
    return has_real_value(get_settings().TAVILY_API_KEY)


def make_chat_model(temperature: float | None = None) -> ChatOpenAI:
    """每次调用新建 ChatOpenAI 实例，避免跨请求共享状态。

    不复用实例的原因：LangChain ChatOpenAI 的内部 token 计数器等状态
    在并发场景下可能互相干扰。
    """
    settings = get_settings()
    return ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """从 LLM 文本响应中提取第一个有效 JSON 对象。

    两阶段策略：
    1. 优先匹配 ```json ... ``` 围栏代码块（LLM 最常使用的格式）
    2. 围栏未命中时退回到括号匹配：取第一个 { 到最后一个 } 之间的内容

    两个候选按优先级依次尝试 json.loads，任一 parse 成功且为 dict 即返回。
    这比单一策略更鲁棒——LLM 有时会忽略围栏指令，有时会在 JSON 前后追加解释文本。
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("LLM response did not contain a valid JSON object")


def _normalize_schema_payload(data: dict[str, Any], schema: type[T]) -> dict[str, Any]:
    """兼容 LLM 将结果额外包在 schema 名外层的情况。

    常见坏格式：
    {
      "FeatureMatrix": {
        "dimensions": [...],
        "matrix": [...]
      }
    }
    或模型误把对象包成单元素数组：
    {
      "feature_matrix": [{
        "dimensions": [...],
        "matrix": [...]
      }]
    }

    Pydantic 期望的是最外层直接为字段对象，因此这里做一层保守解包。
    只有在：
    - 顶层 dict 只有一个 key
    - 且该 key 与 schema 名大小写无关地匹配
    - 且 value 是 dict，或仅包含一个 dict 的 list
    时才会解包，避免误伤正常数据。
    """
    normalized = _normalize_evidence_refs(data)
    if not isinstance(normalized, dict) or len(normalized) != 1:
        return normalized
    [(top_key, inner_value)] = list(normalized.items())

    normalized_key = re.sub(r"[^a-z0-9]+", "", str(top_key).lower())
    schema_name = re.sub(r"[^a-z0-9]+", "", schema.__name__.lower())
    if normalized_key != schema_name:
        return normalized
    if isinstance(inner_value, dict):
        return inner_value
    if (
        isinstance(inner_value, list)
        and len(inner_value) == 1
        and isinstance(inner_value[0], dict)
    ):
        return inner_value[0]
    return normalized


def _normalize_evidence_refs(value: Any) -> Any:
    """Recursively expand URL-only evidence_refs before schema validation."""
    if isinstance(value, list):
        return [_normalize_evidence_refs(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {
        key: _normalize_evidence_refs(item)
        for key, item in value.items()
    }
    refs = normalized.get("evidence_refs")
    if isinstance(refs, list):
        normalized["evidence_refs"] = [
            {"url": ref, "title": ref}
            if isinstance(ref, str)
            else ref
            for ref in refs
        ]
    return normalized


def _schema_repair_prompt(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    schema: type[T],
    raw_content: str,
    error_message: str,
) -> list[tuple[str, str]]:
    """Build a compact repair prompt for malformed structured outputs."""
    compact_invalid_output = raw_content[:12000]
    return [
        (
            "system",
            "\n".join([
                system_prompt.strip(),
                "",
                "你刚才输出的内容没有通过结构化校验。请只返回一个合法 JSON 对象，不要解释，不要 Markdown。",
            ]),
        ),
        (
            "human",
            json.dumps(
                {
                    "original_input": user_payload,
                    "expected_schema": schema.model_json_schema(),
                    "invalid_output": compact_invalid_output,
                    "validation_error": error_message,
                    "repair_rules": [
                        "只返回 JSON 对象本体",
                        "不要添加多余字段",
                        "缺失字段请使用 schema 默认值或空值",
                        "确保字段类型严格匹配 schema",
                    ],
                },
                ensure_ascii=False,
                default=str,
            ),
        ),
    ]


@traceable(run_type="llm", name="invoke_structured_json")
async def invoke_json_model(
    system_prompt: str,
    user_payload: dict[str, Any],
    schema: type[T],
    stream_callback: StreamCallback | None = None,
) -> T:
    """调用 LLM，返回校验后的 Pydantic 结构化对象。

    两种路径：
    - stream_callback=None：ainvoke 一次性获取完整响应
    - stream_callback 传入：astream 逐 chunk 推送，同时累积完整文本用于最终 JSON 解析

    无论哪种路径，都会经过 extract_json_object → schema.model_validate 的校验链。
    迁移到 function calling 后，extract_json_object 可移除，由 with_structured_output 替代。
    """
    llm = make_chat_model()
    messages = [
        ("system", system_prompt),
        ("human", json.dumps(user_payload, ensure_ascii=False, default=str)),
    ]

    async def _invoke(raw_messages: list[tuple[str, str]], allow_stream: bool) -> str:
        if not allow_stream:
            response = await llm.ainvoke(raw_messages)
            content = response.content
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)

        parts: list[str] = []
        async for chunk in llm.astream(raw_messages):
            text = chunk.content
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            if text:
                piece = str(text)
                parts.append(piece)
                await stream_callback(piece)  # type: ignore[misc]
        return "".join(parts)

    content = await _invoke(messages, stream_callback is not None)
    try:
        data = _normalize_schema_payload(extract_json_object(content), schema)
        return schema.model_validate(data)
    except Exception as first_error:
        repair_messages = _schema_repair_prompt(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema=schema,
            raw_content=content,
            error_message=str(first_error),
        )
        repair_response = await llm.ainvoke(repair_messages)
        repair_content = repair_response.content
        if isinstance(repair_content, list):
            repair_content = "".join(part.get("text", "") for part in repair_content if isinstance(part, dict))
        try:
            repaired = _normalize_schema_payload(extract_json_object(str(repair_content)), schema)
            return schema.model_validate(repaired)
        except Exception as second_error:
            raise ValueError(
                f"Structured output validation failed after repair attempt: {first_error}; repair_error: {second_error}"
            ) from second_error


def truncate_text(text: str, limit: int = 1200) -> str:
    """压缩空白并截断文本到指定长度。

    先做 whitespace normalize 再截断，避免因多余空格/换行浪费 token 预算。
    """
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def raw_data_to_context(raw_data: dict[str, list], max_items_per_product: int = 8) -> dict[str, list[dict[str, Any]]]:
    """将原始搜索结果转换为 LLM 友好的上下文格式。

    做三件事：
    1. 每产品最多取 max_items_per_product 条，并优先覆盖不同搜索意图
    2. 只保留 LLM 需要的字段和来源对应的搜索意图
    3. 对 title 和 snippet 做截断，防止单条超长来源撑爆 prompt
    """
    context: dict[str, list[dict[str, Any]]] = {}
    for product, items in raw_data.items():
        context[product] = []
        normalized_items = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in items
        ]
        valid_items = [item for item in normalized_items if isinstance(item, dict)]
        selected: list[dict[str, Any]] = []
        selected_ids: set[int] = set()
        seen_intents: set[str] = set()
        for index, item in enumerate(valid_items):
            intents = item.get("source_intents") or [item.get("source_intent")]
            intents = [str(intent) for intent in intents if intent]
            if any(intent not in seen_intents for intent in intents):
                selected.append(item)
                selected_ids.add(index)
                seen_intents.update(intents)
            if len(selected) >= max_items_per_product:
                break
        if len(selected) < max_items_per_product:
            selected.extend(
                item
                for index, item in enumerate(valid_items)
                if index not in selected_ids
            )

        for item in selected[:max_items_per_product]:
            context[product].append({
                "title": truncate_text(item.get("title", ""), 160),
                "url": item.get("url", ""),
                "snippet": truncate_text(item.get("snippet") or item.get("content_summary") or "", 800),
                "source_intent": item.get("source_intent", ""),
                "source_intents": item.get("source_intents", []),
                "relevance_score": item.get("relevance_score", 0),
            })
    return context
