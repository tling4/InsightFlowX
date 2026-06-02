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
from app.agents.competitor_resolver import normalize_competitor_name, resolve_competitors


# 不同产品类别的搜索意图不同：
# - SaaS: 侧重定价页和用户社区（知乎、少数派）
# - 移动应用: 侧重应用商店评分（Apple Store、酷安）
# - 硬件: 侧重评测和价格追踪（知乎、什么值得买）
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
    """信息采集 Agent：通过 Tavily 搜索 API 并行采集竞品公开信息。

    对每个产品（目标产品 + N 个竞品）并发执行多条搜索查询，
    按 URL 去重后汇总为 raw_data 传入下游分析节点。
    """

    node_name = "information_collection"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}

        target = config.get("target_product", "")
        category = config.get("product_category", "")
        focus_dimensions = config.get("focus_dimensions", [])
        competitor_names = config.get("competitors", []) or []
        competitor_count = config.get("competitor_count", len(competitor_names) or 5)
        competitor_names = competitor_names[:competitor_count]
        # 初始产品列表用于无 Tavily 的兜底路径；Tavily 可用时会先解析并替换竞品。
        products = [p for p in [target, *competitor_names] if p]

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {
                "target_product": target,
                "competitors_count": len(competitor_names),
                "phase": "collecting",
            },
        }, workflow_id)
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="validate_scope",
            message=f"正在校验目标产品与竞品范围，当前目标是 {target or '未命名产品'}。",
        )

        start = time.time()

        raw_data: dict[str, list] = {product: [] for product in products}
        collection_errors: dict[str, str] = {}
        competitors = [CompetitorInfo(name=name, category=category).model_dump(mode="json") for name in competitor_names]

        if not tavily_is_configured():
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="search_unavailable",
                message="未检测到 Tavily 配置，当前将跳过实时搜索，仅保留诊断信息。",
                level="warning",
            )
            for product in products:
                collection_errors[product] = "Tavily API key is not configured; skipped live search."
        else:
            client = AsyncTavilyClient(api_key=get_settings().TAVILY_API_KEY)
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="resolve_competitors",
                message="正在解析有效竞品实体，剔除不适合作为竞品的泛化描述。",
            )
            resolution = await resolve_competitors(
                client=client,
                target_product=target,
                category=category,
                focus_dimensions=focus_dimensions,
                competitor_names=competitor_names,
                competitor_count=competitor_count,
                product_profile=config.get("product_profile"),
            )
            if resolution.dropped or resolution.added:
                await self.log_and_broadcast(event_logger, EventType.TOOL_RESULT, {
                    "tool": "competitor_resolver",
                    "target_product": target,
                    "product_profile": config.get("product_profile"),
                    "subcategory": resolution.subcategory,
                    "query": resolution.query,
                    "original_competitors": competitor_names,
                    "resolved_competitors": resolution.competitors,
                    "dropped": resolution.dropped,
                    "added": resolution.added,
                }, workflow_id)
            competitor_names = resolution.competitors
            config = {**config, "competitors": competitor_names}
            competitors = [
                CompetitorInfo(name=name, category=category).model_dump(mode="json")
                for name in competitor_names
            ]
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="resolved_competitors",
                message=f"已确认 {len(competitor_names)} 个有效竞品，准备开始公开来源采集。",
                level="success",
            )
            minimum_competitors = 1 if competitor_count <= 1 else min(2, competitor_count)
            if len(competitor_names) < minimum_competitors:
                collection_errors["__competitor_resolution__"] = (
                    f"Only resolved {len(competitor_names)} valid competitor(s); "
                    f"at least {minimum_competitors} required before analysis."
                )
                await self.emit_progress(
                    event_logger,
                    workflow_id,
                    stage="insufficient_competitors",
                    message=f"有效竞品数量不足，当前仅确认 {len(competitor_names)} 个，后续分析可能无法继续。",
                    level="warning",
                )
                raw_data = {}
                products = []
            else:
                # 目标产品也参与搜索，确保分析时有自身数据做基线对比。
                products = [p for p in [target, *competitor_names] if p]
                raw_data = {product: [] for product in products}
                await self.emit_progress(
                    event_logger,
                    workflow_id,
                    stage="collect_sources",
                    message=f"正在为 {len(products)} 个产品搜索公开来源，并并发收集可用证据。",
                )
                # 所有产品的搜索并发执行，总耗时 = max(单产品耗时) 而非 sum
                tasks = [
                    self._collect_for_product(client, product, category, focus_dimensions, event_logger, workflow_id)
                    for product in products
                ]
                # gather(return_exceptions=True)：单个产品失败不影响其他产品
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for product, result in zip(products, results):
                    if isinstance(result, Exception):
                        collection_errors[product] = str(result)[:500]
                        raw_data[product] = []
                    else:
                        raw_data[product] = [item.model_dump(mode="json") for item in result]

                missing_sources = [
                    product for product in products
                    if len(raw_data.get(product, [])) == 0
                ]
                missing_competitor_sources = [
                    product for product in missing_sources
                    if product != target
                ]
                if target in missing_sources or missing_competitor_sources:
                    collection_errors["__source_coverage__"] = (
                        "Missing source coverage for: " + ", ".join(missing_sources)
                    )
                    await self.emit_progress(
                        event_logger,
                        workflow_id,
                        stage="source_coverage_warning",
                        message=f"部分产品仍缺少来源覆盖：{', '.join(missing_sources)}。",
                        level="warning",
                    )

        duration_ms = int((time.time() - start) * 1000)
        total_sources = sum(len(items) for items in raw_data.values())
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="collection_complete",
            message=f"已完成采集，共覆盖 {len(raw_data)} 个产品，汇总 {total_sources} 条来源。",
            level="success",
        )

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {
                "collected_competitors": len(raw_data),
                "total_sources": total_sources,
                "failed_competitors": len(collection_errors),
            },
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "config": config,
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
        """对单个产品执行多查询搜索，URL 去重后返回结果列表。

        搜索策略：
        1. 从 SEARCH_QUERY_TEMPLATES 取产品类别对应的 3 条模板查询
        2. 追加一条由用户关注维度拼接的自定义查询
        3. 每条查询取最多 4 条结果，按 URL 去重
        """
        templates = SEARCH_QUERY_TEMPLATES.get(category, SEARCH_QUERY_TEMPLATES["SaaS / 协作工具"])
        focus = " ".join(focus_dimensions[:4]) if focus_dimensions else "功能 定价 用户评价 市场定位"
        queries = [template.format(product=product) for template in templates]
        queries.append(f"{product} {focus}")
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="search_product",
            message=f"正在为 {product} 搜索公开来源并筛选高相关结果。",
        )

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
                if not self._result_mentions_product(product, item):
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
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="summarize_product_sources",
            message=f"{product} 的来源整理完成，当前保留 {len(collected)} 条去重结果。",
            level="success",
        )
        return collected

    def _result_mentions_product(self, product: str, item: dict) -> bool:
        """Keep a search result only when it is visibly about the queried product."""
        product_name = normalize_competitor_name(product)
        if not product_name:
            return False

        title = str(item.get("title") or "")
        content = str(item.get("content") or item.get("snippet") or "")
        text = f"{title}\n{content}".lower()
        product_lower = product_name.lower()
        if product_lower in text:
            return True

        compact_product = product_lower.replace(" ", "")
        compact_text = text.replace(" ", "")
        return bool(compact_product and compact_product in compact_text)
