from app.agents.agent_utils import invoke_json_model, llm_is_configured
from app.schemas.search import SearchQueryPlan, SearchQuerySpec
from app.schemas.workflow import ProductProfile


QUERY_PLANNER_SYSTEM_PROMPT = """你是通用竞争情报搜索规划器。你的任务是把业务分析需求转换成结构化搜索计划。

要求：
- 只返回合法 JSON，不要 Markdown，不要解释。
- 查询模板必须使用 {product} 作为产品名占位符，不得写死任何具体产品名。
- 根据 product_category、product_profile、focus_dimensions 和 extra_requirements 推断领域术语、同义词、证据形态和可能来源。
- 每个 focus_dimension 必须有一个 intent 为 "dimension:<原始维度文本>" 的查询。
- 查询要窄而明确，避免把多个无关维度拼进同一个查询。
- recovery_query_templates 使用不同术语或不同证据路径，不要只是重复主查询。
- preferred_source_types 描述优先来源，例如 official_document、regulation、pricing_page、research_report、news、review、community、dataset。
- 不要假设某类公开信息不存在。
- 总查询数量控制在 3 到 10 条，每个 recovery_query_templates 最多 2 条。
"""


async def build_search_query_plan(
    *,
    product_category: str,
    product_profile: ProductProfile | dict | None,
    focus_dimensions: list[str],
    extra_requirements: str = "",
) -> SearchQueryPlan:
    """Create one reusable plan for the workflow; fall back deterministically."""
    fallback = fallback_search_query_plan(
        product_category=product_category,
        product_profile=product_profile,
        focus_dimensions=focus_dimensions,
        extra_requirements=extra_requirements,
    )
    if not llm_is_configured():
        return fallback

    profile_payload = (
        product_profile.model_dump(mode="json")
        if isinstance(product_profile, ProductProfile)
        else product_profile or {}
    )
    payload = {
        "product_category": product_category,
        "product_profile": profile_payload,
        "focus_dimensions": focus_dimensions[:6],
        "extra_requirements": extra_requirements,
        "required_intents": [f"dimension:{dimension}" for dimension in focus_dimensions[:6]],
        "output_schema": SearchQueryPlan.model_json_schema(),
    }
    try:
        planned = await invoke_json_model(
            QUERY_PLANNER_SYSTEM_PROMPT,
            payload,
            SearchQueryPlan,
        )
    except Exception:
        return fallback
    return _merge_with_required_coverage(planned, fallback, focus_dimensions)


def fallback_search_query_plan(
    *,
    product_category: str,
    product_profile: ProductProfile | dict | None,
    focus_dimensions: list[str],
    extra_requirements: str = "",
) -> SearchQueryPlan:
    """Build a domain-neutral plan without relying on keyword dictionaries."""
    if isinstance(product_profile, ProductProfile):
        profile = product_profile.model_dump(mode="json")
    else:
        profile = product_profile if isinstance(product_profile, dict) else {}
    market_category = str(profile.get("market_category") or product_category or "").strip()
    product_form = str(profile.get("product_form") or "").strip()
    market_context = " ".join(item for item in [market_category, product_form] if item)

    queries = [
        SearchQuerySpec(
            intent="overview",
            query_template=_query("{product}", market_context, "产品介绍 核心能力 使用场景"),
            recovery_query_templates=[_query("{product}", market_context, "overview capabilities use cases")],
            preferred_source_types=["official_document", "research_report"],
        ),
        SearchQuerySpec(
            intent="official",
            query_template=_query("{product}", market_context, "官方 产品文档 帮助中心"),
            recovery_query_templates=[_query("{product}", market_context, "官网 说明 文档")],
            preferred_source_types=["official_document"],
        ),
        SearchQuerySpec(
            intent="independent_evidence",
            query_template=_query("{product}", market_context, "对比 评测 用户评价"),
            recovery_query_templates=[_query("{product}", market_context, "analysis review comparison")],
            preferred_source_types=["research_report", "review", "community"],
        ),
    ]

    for raw_dimension in focus_dimensions[:6]:
        dimension = " ".join(str(raw_dimension).split())
        if not dimension:
            continue
        queries.append(SearchQuerySpec(
            intent=f"dimension:{dimension}",
            dimension=dimension,
            query_template=_query("{product}", market_context, dimension, "官方 说明 数据 案例"),
            recovery_query_templates=[
                _query("{product}", market_context, dimension, "报告 评测 讨论"),
                _query("{product}", market_context, dimension, "documentation report review"),
            ],
            preferred_source_types=["official_document", "research_report", "news", "review"],
        ))

    requirement = " ".join(str(extra_requirements).split())[:160]
    if requirement:
        queries.append(SearchQuerySpec(
            intent="business_context",
            query_template=_query("{product}", market_context, requirement, "资料 案例"),
            recovery_query_templates=[_query("{product}", market_context, requirement, "报告 讨论")],
            preferred_source_types=["official_document", "research_report", "news"],
        ))

    return SearchQueryPlan(
        strategy_summary="通用回退计划：按概览、官方来源、独立证据和关注维度分别检索。",
        queries=_dedupe_specs(queries),
    )


def _merge_with_required_coverage(
    planned: SearchQueryPlan,
    fallback: SearchQueryPlan,
    focus_dimensions: list[str],
) -> SearchQueryPlan:
    required = {f"dimension:{' '.join(str(item).split())}" for item in focus_dimensions[:6] if str(item).strip()}
    planned_specs = _dedupe_specs(planned.queries[:10])
    planned_by_intent = {spec.intent: spec for spec in planned_specs}
    fallback_by_intent = {spec.intent: spec for spec in fallback.queries}
    prioritized_intents = ["overview", "official", "independent_evidence", *sorted(required), "business_context"]
    merged: list[SearchQuerySpec] = []
    for intent in prioritized_intents:
        fallback_spec = fallback_by_intent.get(intent)
        spec = planned_by_intent.get(intent) or fallback_spec
        if spec is None:
            continue
        if not spec.recovery_query_templates and fallback_spec is not None:
            spec = spec.model_copy(update={"recovery_query_templates": fallback_spec.recovery_query_templates})
        merged.append(spec)
    merged.extend(spec for spec in planned_specs if spec.intent not in prioritized_intents)

    return SearchQueryPlan(
        strategy_summary=planned.strategy_summary or fallback.strategy_summary,
        queries=_dedupe_specs(merged)[:10],
    )


def _query(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _dedupe_specs(specs: list[SearchQuerySpec]) -> list[SearchQuerySpec]:
    seen_templates: set[str] = set()
    seen_intents: set[str] = set()
    deduped: list[SearchQuerySpec] = []
    for spec in specs:
        if spec.query_template in seen_templates or spec.intent in seen_intents:
            continue
        seen_templates.add(spec.query_template)
        seen_intents.add(spec.intent)
        deduped.append(spec)
    return deduped
