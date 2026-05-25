import json
import re
from typing import Any, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import get_settings


T = TypeVar("T", bound=BaseModel)


def has_real_value(value: str | None) -> bool:
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
    settings = get_settings()
    return ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from an LLM response."""
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


async def invoke_json_model(system_prompt: str, user_payload: dict[str, Any], schema: type[T]) -> T:
    llm = make_chat_model()
    response = await llm.ainvoke([
        ("system", system_prompt),
        ("human", json.dumps(user_payload, ensure_ascii=False, default=str)),
    ])
    content = response.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    data = extract_json_object(str(content))
    return schema.model_validate(data)


def truncate_text(text: str, limit: int = 1200) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def raw_data_to_context(raw_data: dict[str, list], max_items_per_product: int = 5) -> dict[str, list[dict[str, Any]]]:
    context: dict[str, list[dict[str, Any]]] = {}
    for product, items in raw_data.items():
        context[product] = []
        for item in items[:max_items_per_product]:
            if isinstance(item, BaseModel):
                item = item.model_dump(mode="json")
            if not isinstance(item, dict):
                continue
            context[product].append({
                "title": truncate_text(item.get("title", ""), 160),
                "url": item.get("url", ""),
                "snippet": truncate_text(item.get("snippet") or item.get("content_summary") or "", 800),
                "relevance_score": item.get("relevance_score", 0),
            })
    return context
