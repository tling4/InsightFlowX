import time
import asyncio
from datetime import datetime
from tavily import AsyncTavilyClient
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import tavily_is_configured
from app.config import get_settings
from app.core.runtime.context import AgentContext
from app.schemas.event import EventType
from app.schemas.competitor import CompetitorInfo, SearchResult
from app.schemas.search import SearchQueryPlan
from app.agents.competitor_resolver import normalize_competitor_name, resolve_competitors
from app.agents.query_planner import build_search_query_plan


MIN_PRODUCT_SOURCES = 6
MAX_RECOVERY_QUERIES = 6


class CollectionAgent(BaseAgent):
    """信息采集 Agent：通过 Tavily 搜索 API 并行采集竞品公开信息。

    对每个产品（目标产品 + N 个竞品）并发执行多条搜索查询，
    按 URL 去重后汇总为 raw_data 传入下游分析节点。
    """

    node_name = "information_collection"

    async def run(self, state: dict, ctx: AgentContext) -> dict:
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

        await self.log_and_broadcast(ctx, EventType.NODE_START, {
            "input_summary": {
                "target_product": target,
                "competitors_count": len(competitor_names),
                "phase": "collecting",
            },
        })
        await self.emit_progress(
            ctx,
            stage="validate_scope",
            message=f"正在校验目标产品与竞品范围，当前目标是 {target or '未命名产品'}。",
        )

        start = time.time()

        raw_data: dict[str, list] = {product: [] for product in products}
        collection_errors: dict[str, str] = {}
        search_plan: SearchQueryPlan | None = None
        search_coverage: dict[str, dict] = {}
        competitors = [CompetitorInfo(name=name, category=category).model_dump(mode="json") for name in competitor_names]

        if not tavily_is_configured():
            await self.emit_progress(
                ctx,
                stage="search_unavailable",
                message="未检测到 Tavily 配置，当前将跳过实时搜索，仅保留诊断信息。",
                level="warning",
            )
            for product in products:
                collection_errors[product] = "Tavily API key is not configured; skipped live search."
        else:
            client = AsyncTavilyClient(api_key=get_settings().TAVILY_API_KEY)
            await self.emit_progress(
                ctx,
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
                await self.log_and_broadcast(ctx, EventType.TOOL_RESULT, {
                    "tool": "competitor_resolver",
                    "target_product": target,
                    "product_profile": config.get("product_profile"),
                    "subcategory": resolution.subcategory,
                    "query": resolution.query,
                    "original_competitors": competitor_names,
                    "resolved_competitors": resolution.competitors,
                    "dropped": resolution.dropped,
                    "added": resolution.added,
                })
            competitor_names = resolution.competitors
            config = {**config, "competitors": competitor_names}
            competitors = [
                CompetitorInfo(name=name, category=category).model_dump(mode="json")
                for name in competitor_names
            ]
            await self.emit_progress(
                ctx,
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
                    ctx,
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
                    ctx,
                    stage="plan_queries",
                    message="正在根据产品画像、分析维度和业务问题生成结构化搜索计划。",
                )
                search_plan = await build_search_query_plan(
                    product_category=category,
                    product_profile=config.get("product_profile"),
                    focus_dimensions=focus_dimensions,
                    extra_requirements=config.get("extra_requirements", ""),
                )
                await self.log_and_broadcast(ctx, EventType.TOOL_RESULT, {
                    "tool": "query_planner",
                    "strategy_summary": search_plan.strategy_summary,
                    "query_count": len(search_plan.queries),
                    "intents": [spec.intent for spec in search_plan.queries],
                })
                await self.emit_progress(
                    ctx,
                    stage="collect_sources",
                    message=f"正在为 {len(products)} 个产品搜索公开来源，并并发收集可用证据。",
                )
                # 所有产品的搜索并发执行，总耗时 = max(单产品耗时) 而非 sum
                tasks = [
                    self._collect_for_product(client, product, search_plan, ctx)
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
                search_coverage = self._build_search_coverage(raw_data, search_plan)

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
                        ctx,
                        stage="source_coverage_warning",
                        message=f"部分产品仍缺少来源覆盖：{', '.join(missing_sources)}。",
                        level="warning",
                    )

        duration_ms = int((time.time() - start) * 1000)
        total_sources = sum(len(items) for items in raw_data.values())
        await self.emit_progress(
            ctx,
            stage="collection_complete",
            message=f"已完成采集，共覆盖 {len(raw_data)} 个产品，汇总 {total_sources} 条来源。",
            level="success",
        )

        await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
            "output_summary": {
                "collected_competitors": len(raw_data),
                "total_sources": total_sources,
                "failed_competitors": len(collection_errors),
                "products_with_dimension_gaps": sum(
                    1 for coverage in search_coverage.values()
                    if coverage.get("missing_dimensions")
                ),
            },
            "duration_ms": duration_ms,
        })

        return {
            "config": config,
            "raw_data": raw_data,
            "collection_errors": collection_errors,
            "competitors": competitors,
            "search_plan": search_plan.model_dump(mode="json") if search_plan else {},
            "search_coverage": search_coverage,
            "context_summaries": {},
            "current_phase": "collecting",
        }

    async def _collect_for_product(
        self,
        client: AsyncTavilyClient,
        product: str,
        search_plan: SearchQueryPlan,
        ctx: AgentContext,
    ) -> list[SearchResult]:
        """对单个产品执行多查询搜索，URL 去重后返回结果列表。

        搜索策略：
        1. 渲染工作流级 Query Planner 生成的结构化计划
        2. 执行按意图拆分的窄查询
        3. 对未覆盖维度和低总召回执行规划器提供的补救查询
        """
        queries = self._render_query_plan(product, search_plan)
        await self.emit_progress(
            ctx,
            stage="search_product",
            message=f"正在为 {product} 搜索公开来源并筛选高相关结果。",
        )

        await self.log_and_broadcast(ctx, EventType.TOOL_CALL, {
            "tool": "tavily.search",
            "product": product,
            "queries": [query for _, query in queries],
        })

        collected_by_url: dict[str, SearchResult] = {}
        collected: list[SearchResult] = []
        for intent, query in queries:
            response = await client.search(
                query=query,
                max_results=4,
                search_depth="advanced",
                include_answer=False,
            )
            for item in response.get("results", []):
                url = item.get("url", "")
                if not url:
                    continue
                if not self._result_is_relevant(product, item, query):
                    continue
                if url in collected_by_url:
                    existing = collected_by_url[url]
                    if intent not in existing.source_intents:
                        existing.source_intents.append(intent)
                    continue
                result = SearchResult(
                    url=url,
                    title=item.get("title") or url,
                    snippet=item.get("content") or item.get("snippet") or "",
                    content_summary=item.get("content"),
                    source_query=query,
                    source_intent=intent,
                    source_intents=[intent],
                    relevance_score=float(item.get("score") or 0),
                    retrieved_at=datetime.utcnow(),
                )
                collected_by_url[url] = result
                collected.append(result)

        covered_intents = {
            intent
            for item in collected
            for intent in (item.source_intents or ([item.source_intent] if item.source_intent else []))
        }
        fallback_queries = self._build_recovery_query_plan(
            product,
            search_plan,
            covered_intents,
            len(collected),
        )
        if fallback_queries:
            for intent, query in fallback_queries:
                response = await client.search(
                    query=query,
                    max_results=6,
                    search_depth="advanced",
                    include_answer=False,
                )
                for item in response.get("results", []):
                    url = item.get("url", "")
                    if not url or not self._result_is_relevant(product, item, query):
                        continue
                    if url in collected_by_url:
                        existing = collected_by_url[url]
                        if intent not in existing.source_intents:
                            existing.source_intents.append(intent)
                        continue
                    result = SearchResult(
                        url=url,
                        title=item.get("title") or url,
                        snippet=item.get("content") or item.get("snippet") or "",
                        content_summary=item.get("content"),
                        source_query=query,
                        source_intent=intent,
                        source_intents=[intent],
                        relevance_score=float(item.get("score") or 0),
                        retrieved_at=datetime.utcnow(),
                    )
                    collected_by_url[url] = result
                    collected.append(result)

        collected.sort(key=lambda item: item.relevance_score, reverse=True)
        await self.log_and_broadcast(ctx, EventType.TOOL_RESULT, {
            "tool": "tavily.search",
            "product": product,
            "source_count": len(collected),
            "covered_intents": sorted({
                intent
                for item in collected
                for intent in (item.source_intents or ([item.source_intent] if item.source_intent else []))
            }),
        })
        await self.emit_progress(
            ctx,
            stage="summarize_product_sources",
            message=f"{product} 的来源整理完成，当前保留 {len(collected)} 条去重结果。",
            level="success",
        )
        return collected

    def _render_query_plan(
        self,
        product: str,
        search_plan: SearchQueryPlan,
    ) -> list[tuple[str, str]]:
        """Render one workflow-level plan for a concrete product."""
        return self._dedupe_query_plan([
            (spec.intent, spec.query_template.format(product=product))
            for spec in search_plan.queries
        ])

    def _build_recovery_query_plan(
        self,
        product: str,
        search_plan: SearchQueryPlan,
        covered_intents: set[str],
        source_count: int,
    ) -> list[tuple[str, str]]:
        """Use planner-provided alternatives for uncovered or weakly covered intents."""
        queries: list[tuple[str, str]] = []
        uncovered_specs = [spec for spec in search_plan.queries if spec.intent not in covered_intents]
        uncovered_specs.sort(key=lambda spec: (not spec.intent.startswith("dimension:"), spec.intent))
        for recovery_index in range(2):
            for spec in uncovered_specs:
                if recovery_index < len(spec.recovery_query_templates):
                    queries.append((
                        spec.intent,
                        spec.recovery_query_templates[recovery_index].format(product=product),
                    ))

        if source_count < MIN_PRODUCT_SOURCES:
            for spec in search_plan.queries:
                if spec.intent in {"official", "independent_evidence", "overview"}:
                    queries.extend(
                        (spec.intent, template.format(product=product))
                        for template in spec.recovery_query_templates
                    )
        return self._dedupe_query_plan(queries)[:MAX_RECOVERY_QUERIES]

    @staticmethod
    def _dedupe_query_plan(queries: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen: set[str] = set()
        deduped: list[tuple[str, str]] = []
        for intent, query in queries:
            if query in seen:
                continue
            seen.add(query)
            deduped.append((intent, query))
        return deduped

    def _result_is_relevant(self, product: str, item: dict, query: str) -> bool:
        """Accept explicit entity matches and high-confidence search-engine matches.

        Official help pages often omit the parent product name from their title and
        snippet. Requiring a literal mention dropped those valuable narrow sources.
        """
        if self._result_mentions_product(product, item):
            return True
        score = float(item.get("score") or 0)
        return score >= 0.55 and normalize_competitor_name(product).lower() in query.lower()

    @staticmethod
    def _build_search_coverage(raw_data: dict[str, list], search_plan: SearchQueryPlan) -> dict[str, dict]:
        planned_intents = [spec.intent for spec in search_plan.queries]
        dimension_intents = {intent for intent in planned_intents if intent.startswith("dimension:")}
        coverage: dict[str, dict] = {}
        for product, items in raw_data.items():
            covered = {
                intent
                for item in items
                if isinstance(item, dict)
                for intent in (item.get("source_intents") or [item.get("source_intent")])
                if intent
            }
            missing = [intent for intent in planned_intents if intent not in covered]
            coverage[product] = {
                "source_count": len(items),
                "covered_intents": sorted(covered),
                "missing_intents": missing,
                "missing_dimensions": [
                    intent.removeprefix("dimension:")
                    for intent in missing
                    if intent in dimension_intents
                ],
            }
        return coverage

    def _result_mentions_product(self, product: str, item: dict) -> bool:
        """Return whether a search result visibly mentions the queried product."""
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
