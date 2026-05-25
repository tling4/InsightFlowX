import time
import uuid
import asyncio
from datetime import datetime
from tavily import AsyncTavilyClient
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import tavily_is_configured
from app.config import get_settings
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.competitor import CompetitorInfo, SearchResult


SEARCH_QUERY_TEMPLATES = {
    "SaaS / 协作工具": [
        "{product} 功能 定价 用户评价",
        "{product} 竞品 对比 优缺点",
        "{product} pricing features reviews",
    ],
    "移动应用": [
        "{product} 功能 评分 用户评价",
        "{product} App 体验 优缺点",
        "{product} app pricing reviews",
    ],
    "硬件产品": [
        "{product} 参数 价格 评测",
        "{product} 优缺点 用户评价",
        "{product} specs price review",
    ],
}


class CollectionAgent(BaseAgent):
    node_name = "information_collection"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Collect competitive intelligence with Tavily search."""
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}

        target = config.get("target_product", "")
        category = config.get("product_category", "")
        focus_dimensions = config.get("focus_dimensions", [])
        competitor_names = config.get("competitors", []) or []
        competitor_count = config.get("competitor_count", len(competitor_names) or 5)
        competitor_names = competitor_names[:competitor_count]
        products = [p for p in [target, *competitor_names] if p]

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {
                "target_product": target,
                "competitors_count": len(competitor_names),
                "phase": "collecting",
            },
        }, workflow_id)

        start = time.time()

        raw_data: dict[str, list] = {product: [] for product in products}
        collection_errors: dict[str, str] = {}
        competitors = [CompetitorInfo(name=name, category=category).model_dump(mode="json") for name in competitor_names]

        if not tavily_is_configured():
            for product in products:
                collection_errors[product] = "Tavily API key is not configured; skipped live search."
        else:
            client = AsyncTavilyClient(api_key=get_settings().TAVILY_API_KEY)
            tasks = [
                self._collect_for_product(client, product, category, focus_dimensions, event_logger, workflow_id)
                for product in products
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for product, result in zip(products, results):
                if isinstance(result, Exception):
                    collection_errors[product] = str(result)[:500]
                    raw_data[product] = []
                else:
                    raw_data[product] = [item.model_dump(mode="json") for item in result]

        duration_ms = int((time.time() - start) * 1000)
        total_sources = sum(len(items) for items in raw_data.values())

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {
                "collected_competitors": len(raw_data),
                "total_sources": total_sources,
                "failed_competitors": len(collection_errors),
            },
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "raw_data": raw_data,
            "collection_errors": collection_errors,
            "competitors": competitors,
            "context_summaries": {},
            "current_phase": "collecting",
        }

    async def _collect_for_product(
        self,
        client: AsyncTavilyClient,
        product: str,
        category: str,
        focus_dimensions: list[str],
        event_logger: EventLogger,
        workflow_id: uuid.UUID,
    ) -> list[SearchResult]:
        templates = SEARCH_QUERY_TEMPLATES.get(category, SEARCH_QUERY_TEMPLATES["SaaS / 协作工具"])
        focus = " ".join(focus_dimensions[:4]) if focus_dimensions else "功能 定价 用户评价 市场定位"
        queries = [template.format(product=product) for template in templates]
        queries.append(f"{product} {focus}")

        await self.log_and_broadcast(event_logger, EventType.TOOL_CALL, {
            "tool": "tavily.search",
            "product": product,
            "queries": queries,
        }, workflow_id)

        seen_urls: set[str] = set()
        collected: list[SearchResult] = []
        for query in queries:
            response = await client.search(
                query=query,
                max_results=4,
                search_depth="advanced",
                include_answer=False,
            )
            for item in response.get("results", []):
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                collected.append(SearchResult(
                    url=url,
                    title=item.get("title") or url,
                    snippet=item.get("content") or item.get("snippet") or "",
                    content_summary=item.get("content"),
                    relevance_score=float(item.get("score") or 0),
                    retrieved_at=datetime.utcnow(),
                ))

        await self.log_and_broadcast(event_logger, EventType.TOOL_RESULT, {
            "tool": "tavily.search",
            "product": product,
            "source_count": len(collected),
        }, workflow_id)
        return collected
