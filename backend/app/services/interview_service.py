import uuid
from typing import List, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from tavily import AsyncTavilyClient
from app.config import get_settings
from app.db.models.workflow import InterviewMessageModel
from app.db.queries.workflow_queries import get_workflow_by_uuid, get_message_history
from app.agents.interview_agent import InterviewAgent

settings = get_settings()
tavily_client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
interview_agent = InterviewAgent()


def convert_to_langchain_messages(history: List[InterviewMessageModel]) -> List[BaseMessage]:
    messages: List[BaseMessage] = []
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))
    return messages


async def save_message(db: AsyncSession, workflow_id: uuid.UUID, role: str, content: str):
    message = InterviewMessageModel(
        workflow_id=workflow_id,
        role=role,
        content=content
    )
    db.add(message)
    await db.commit()


async def suggest_competitors(target_product: str, category: str) -> List[str]:
    try:
        query = f"与{target_product}同类的主流竞品产品有哪些，只返回产品名称列表，不返回其他内容"
        result = await tavily_client.search(query, max_results=3)
        competitors = []
        for res in result.get("results", []):
            for text in [res.get("title", ""), res.get("content", "")]:
                for line in text.replace("、", "\n").replace("，", "\n").replace("。", "\n").split("\n"):
                    name = line.strip().strip("[]()（）【】\"'")
                    if name and name != target_product and len(name) < 30 and name not in competitors:
                        competitors.append(name)
        return competitors[:5]
    except Exception:
        return []


async def stream_interview_response(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    user_message: str
) -> AsyncGenerator[str, None]:
    await save_message(db, workflow_id, "user", user_message)
    history = await get_message_history(db, workflow_id)
    lc_messages = convert_to_langchain_messages(history)

    full_response = ""
    async for chunk in interview_agent.stream_response(lc_messages):
        full_response += chunk
        yield chunk

    await save_message(db, workflow_id, "assistant", full_response)

    config = interview_agent.try_extract_config(full_response)
    is_complete = interview_agent.is_complete_signal(full_response)

    if config:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if workflow:
            if not config.competitors:
                config.competitors = await suggest_competitors(config.target_product, config.product_category)
            workflow.config = config.model_dump()
            await db.commit()

    yield "\n---META---\n"
    import json
    meta = {
        "is_complete": is_complete,
        "extracted_config": config.model_dump() if config else None,
        "suggested_competitors": config.competitors if config else []
    }
    yield json.dumps(meta, ensure_ascii=False)
