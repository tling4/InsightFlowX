import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.workflow import ProductProfile


class SearchClient(Protocol):
    async def search(self, query: str, max_results: int = 5, **kwargs): ...


@dataclass(frozen=True)
class ResolverStrategy:
    name: str
    query_terms: list[str]
    target_hints: set[str]
    valid_patterns: list[str] = field(default_factory=list)
    valid_hints: set[str] = field(default_factory=set)
    invalid_keywords: set[str] = field(default_factory=set)


BASE_INVALID_KEYWORDS = {
    "媒体",
    "新聞",
    "新闻",
    "频道",
    "博客",
    "论坛",
    "圖書館",
    "图书馆",
    "学习法",
    "學習法",
    "系统化",
    "系統化",
    "校正",
    "校准",
    "電腦王",
    "电脑王",
    "阿達",
    "运营商",
    "運營商",
    "电信",
    "電信",
    "所以",
    "我用",
    "準備",
    "准备",
    "好多年",
    "想换",
    "想換",
    "至于",
    "或者",
    "以及",
}

GENERIC_CATEGORY_TERMS = {
    "app",
    "应用",
    "工具",
    "产品",
    "平台",
    "服务",
    "软件",
    "硬件",
    "内容",
    "社区",
    "社交",
    "电商",
    "品牌",
    "品类",
    "赛道",
    "领域",
    "方向",
    "场景",
    "攻略",
    "旅游",
    "探店",
    "种草",
    "点评",
    "本地生活",
}

GENERIC_DESCRIPTOR_MARKERS = {
    "或者",
    "或是",
    "以及",
    "还有",
    "至于",
    "这类",
    "类似",
    "同类",
    "垂直",
    "主流",
    "相关",
    "品类",
    "类型",
    "类别",
    "赛道",
    "领域",
    "方向",
    "场景",
    "类产品",
    "类app",
    "类应用",
}

GENERIC_RELATION_MARKERS = {
    "竞品",
    "竞争对手",
    "对标",
    "对比",
    "替代",
    "同类",
    "类似",
    "alternatives",
    "competitors",
    "competition",
    "vs",
}


SMARTPHONE_PATTERNS = [
    r"\bOPPO\s*Find\s*X\d+\s*(?:Ultra|Pro)?\b",
    r"\bvivo\s*X\d+\s*(?:Ultra|Pro)?\b",
    r"(?:荣耀|Honor)\s*Magic\s*\d+\s*(?:RSR|Pro)?",
    r"(?:三星|Samsung)\s*(?:Galaxy\s*)?S\d+\s*(?:Ultra|Plus|Pro)?",
    r"(?:华为|Huawei)\s*(?:Pura|Mate)\s*\d+\s*(?:Ultra|Pro\+?|Pro)?",
    r"\bPixel\s*\d+\s*(?:Pro\s*XL|Pro|XL)?\b",
    r"\biPhone\s*\d+\s*(?:Pro\s*Max|Pro|Plus|Mini|Air)?\b",
    r"(?:小米|Xiaomi)\s*\d+\s*(?:Ultra|Pro)?",
    r"(?:一加|OnePlus)\s*\d+\s*(?:Pro)?",
    r"\brealme\s*GT\d+\s*(?:Pro)?\b",
]

DRONE_PATTERNS = [
    r"\bDJI\s*(?:Mavic|Air|Mini)\s*\d*\s*(?:S|Pro|Pro\s*Max)?\b",
    r"(?:大疆|DJI)\s*(?:Mavic|Air|Mini|Avata)\s*\d*\s*(?:S|Pro)?",
    r"\bAutel\s*EVO\s*(?:Lite|Nano|II|Max)?\s*\w*\b",
    r"\bSkydio\s*\d+\b",
    r"\bHoverAir\s*X\d+\s*(?:Pro|ProMax)?\b",
]

SAAS_WORKSPACE_PATTERNS = [
    r"\bNotion\b",
    r"\bCoda\b",
    r"\bConfluence\b",
    r"\bClickUp\b",
    r"\bAsana\b",
    r"\bAirtable\b",
    r"\bMonday\.com\b",
    r"\bSlack\b",
    r"\bMicrosoft\s*Loop\b",
    r"\bGoogle\s*Docs\b",
    r"(?:飞书|飛書)",
    r"(?:语雀|語雀)",
    r"(?:腾讯文档|騰訊文檔)",
]


STRATEGIES = {
    "smartphone": ResolverStrategy(
        name="smartphone",
        query_terms=["同档", "竞品", "对比", "旗舰", "手机", "影像"],
        target_hints={"手机", "iphone", "galaxy", "小米", "xiaomi", "oppo", "vivo", "荣耀", "honor", "华为", "huawei", "ultra"},
        valid_patterns=SMARTPHONE_PATTERNS,
        valid_hints={"手机", "旗舰", "影像", "配置", "参数", "续航", "快充", "骁龙", "ultra", "pro", "max", "galaxy", "iphone", "pixel", "find", "magic", "mate", "pura"},
        invalid_keywords=BASE_INVALID_KEYWORDS | {"电视", "tv", "google tv"},
    ),
    "drone": ResolverStrategy(
        name="drone",
        query_terms=["同类", "竞品", "对比", "无人机", "航拍", "云台"],
        target_hints={"无人机", "航拍", "大疆", "dji", "mavic", "air", "mini", "avata"},
        valid_patterns=DRONE_PATTERNS,
        valid_hints={"无人机", "航拍", "云台", "避障", "图传", "续航", "dji", "大疆", "mavic", "air", "mini", "autel", "evo", "skydio", "hoverair"},
        invalid_keywords=BASE_INVALID_KEYWORDS | {"手机", "电视", "tv"},
    ),
    "saas_workspace": ResolverStrategy(
        name="saas_workspace",
        query_terms=["alternatives", "competitors", "竞品", "协作文档", "知识库", "项目管理"],
        target_hints={"notion", "飞书", "飛書", "confluence", "coda", "clickup", "airtable", "workspace", "协作", "文档", "知识库"},
        valid_patterns=SAAS_WORKSPACE_PATTERNS,
        valid_hints={"workspace", "docs", "wiki", "project", "management", "协作", "文档", "知识库", "项目", "任务", "notion", "coda", "confluence", "clickup", "飞书", "语雀"},
        invalid_keywords=BASE_INVALID_KEYWORDS | {"手机", "无人机", "电视", "tv"},
    ),
    "generic": ResolverStrategy(
        name="generic",
        query_terms=["同类", "竞品", "对比", "替代品"],
        target_hints=set(),
        valid_patterns=[],
        valid_hints=set(),
        invalid_keywords=BASE_INVALID_KEYWORDS,
    ),
}


@dataclass
class CompetitorResolution:
    competitors: list[str]
    dropped: list[dict[str, str]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    query: str = ""
    subcategory: str = "generic"


def normalize_competitor_name(name: str) -> str:
    return " ".join(str(name).replace("　", " ").split()).strip(" ,，、。;；|｜")


PROFILE_CATEGORY_ALIASES = {
    "smartphone": {"smartphone", "mobile phone", "phone", "手机", "智能手机", "旗艦手機", "旗舰手机"},
    "drone": {"drone", "camera drone", "无人机", "無人機", "航拍"},
    "saas_workspace": {
        "productivity saas",
        "workspace",
        "collaboration software",
        "collaboration saas",
        "knowledge base",
        "project management",
        "协作",
        "協作",
        "知识库",
        "知識庫",
    },
}


def detect_subcategory(target_product: str, category: str, product_profile: ProductProfile | dict[str, Any] | None = None) -> str:
    profile_category = _profile_value(product_profile, "market_category").lower()
    profile_form = _profile_value(product_profile, "product_form").lower()
    profile_text = f"{profile_category} {profile_form}"
    for name, aliases in PROFILE_CATEGORY_ALIASES.items():
        if _contains_any(profile_text, aliases):
            return name

    lowered = normalize_competitor_name(target_product).lower()
    if category in {"硬件产品", "硬件 / 消费电子"}:
        if _contains_any(lowered, STRATEGIES["drone"].target_hints):
            return "drone"
        if _contains_any(lowered, STRATEGIES["smartphone"].target_hints):
            return "smartphone"
        return "generic"
    if category in {"SaaS / 协作工具", "企业软件 / SaaS", "AI 产品 / 智能助手"}:
        if _contains_any(lowered, STRATEGIES["saas_workspace"].target_hints):
            return "saas_workspace"
        return "generic"
    if category in {"移动应用", "平台 / 社区 / 内容", "电商 / 零售 / 本地生活"}:
        return "generic"
    return "generic"


def is_valid_competitor_name(
    name: str,
    target_product: str,
    category: str,
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> tuple[bool, str]:
    strategy = STRATEGIES[detect_subcategory(target_product, category, product_profile)]
    return _is_valid_for_strategy(name, target_product, strategy, product_profile)


def _is_valid_for_strategy(
    name: str,
    target_product: str,
    strategy: ResolverStrategy,
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> tuple[bool, str]:
    normalized = normalize_competitor_name(name)
    if not normalized:
        return False, "empty_name"
    if normalized == normalize_competitor_name(target_product):
        return False, "same_as_target"
    if _product_signature(normalized) and _product_signature(normalized) == _product_signature(target_product):
        return False, "same_as_target"

    lowered = normalized.lower()
    if strategy.name == "generic" and _looks_like_category_descriptor(normalized):
        return False, "category_descriptor"
    if _looks_like_non_product_phrase(normalized):
        return False, "looks_like_non_product_phrase"
    if _looks_like_gibberish_entity(normalized):
        return False, "looks_like_gibberish_entity"
    if _looks_like_same_series_variant(normalized, target_product, product_profile):
        return False, "same_series_variant"
    if any(keyword in lowered for keyword in strategy.invalid_keywords):
        return False, "looks_like_non_product_entity"
    if len(normalized) > 40:
        return False, "name_too_long"
    if matches_strategy_pattern(normalized, strategy):
        if strategy.name == "smartphone" and _looks_like_tier_mismatch(normalized, target_product, product_profile):
            return False, "tier_mismatch"
        return True, f"{strategy.name}_pattern"
    if strategy.valid_hints and _contains_any(lowered, strategy.valid_hints):
        if strategy.name == "smartphone" and _looks_like_tier_mismatch(normalized, target_product, product_profile):
            return False, "tier_mismatch"
        return True, f"{strategy.name}_hint"
    if strategy.name == "generic":
        if not _has_generic_entity_signal(normalized):
            return False, "missing_product_entity_signal"
        return True, "accepted"
    return False, f"missing_{strategy.name}_product_hint"


def matches_smartphone_pattern(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SMARTPHONE_PATTERNS)


def matches_strategy_pattern(text: str, strategy: ResolverStrategy) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in strategy.valid_patterns)


def _product_signature(name: str) -> str:
    lowered = normalize_competitor_name(name).lower()
    number = re.search(r"\d+", lowered)
    if not number:
        return ""
    suffixes = [suffix for suffix in ("ultra", "pro max", "pro", "max", "air", "mini") if suffix in lowered]
    return " ".join([number.group(0), *suffixes]).strip()


def extract_candidate_names(text: str, strategy: ResolverStrategy | None = None) -> list[str]:
    if strategy and strategy.name == "generic":
        return extract_generic_candidate_names(text)

    patterns = strategy.valid_patterns if strategy else [
        *SMARTPHONE_PATTERNS,
        *DRONE_PATTERNS,
        *SAAS_WORKSPACE_PATTERNS,
    ]
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            matches.append((match.start(), normalize_competitor_name(match.group(0))))
    candidates = [value for _, value in sorted(matches, key=lambda item: item[0])]
    return _dedupe_preserve_order(candidates)


def extract_generic_candidate_names(text: str) -> list[str]:
    """Extract likely product entities from evidence text for unknown categories.

    This is deliberately conservative: generic extraction only trusts lines that
    look like they are naming alternatives/competitors, then validates each
    fragment with the same product-entity guards used for user input.
    """
    candidates: list[str] = []
    for line in text.splitlines():
        normalized_line = " ".join(line.split())
        if not normalized_line:
            continue

        lowered = normalized_line.lower()
        if not any(marker in lowered for marker in GENERIC_RELATION_MARKERS):
            continue

        segments = []
        for marker in ("：", ":", "包括", "include", "includes", "such as"):
            if marker in normalized_line:
                segments.append(normalized_line.split(marker, 1)[1])
        segments.append(normalized_line)

        for segment in segments:
            for fragment in re.split(r"[、，,;；|｜/／]|\s+(?:和|与|及|以及|or|and)\s+", segment):
                candidate = _clean_generic_candidate_fragment(fragment)
                if candidate:
                    candidates.append(candidate)

    return _dedupe_preserve_order(candidates)


def _clean_generic_candidate_fragment(fragment: str) -> str:
    value = normalize_competitor_name(fragment)
    if not value:
        return ""
    value = re.sub(r"\[[^\]]+\]|\([^)]*\)|（[^）]*）", "", value)
    value = re.sub(r"^(竞品|竞争对手|替代品|对标产品|类似产品|同类产品|包括|还有|如|例如)\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(等|等产品|等平台|等应用|等工具)$", "", value)
    value = re.sub(r"\s+(App|APP|app|应用|官网|官方网站)$", "", value)
    value = normalize_competitor_name(value)

    # Remove relation words that remain attached to the target side of a title,
    # e.g. "小红书竞品" from "小红书竞品：大众点评、马蜂窝".
    if any(marker in value.lower() for marker in GENERIC_RELATION_MARKERS):
        return ""
    if len(value) > 30:
        return ""
    return value


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_competitor_name(value)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _contains_any(text: str, hints: set[str]) -> bool:
    return any(hint.lower() in text for hint in hints)


def _profile_value(product_profile: ProductProfile | dict[str, Any] | None, key: str) -> str:
    if isinstance(product_profile, ProductProfile):
        value = getattr(product_profile, key, "")
    elif isinstance(product_profile, dict):
        value = product_profile.get(key, "")
    else:
        value = ""
    return str(value or "").strip()


def _normalized_variant_tier(value: str) -> str:
    lowered = normalize_competitor_name(value).lower().replace("_", " ").replace("-", " ")
    if not lowered:
        return ""
    if "pro max" in lowered or "promax" in lowered:
        return "pro max"
    if "ultra" in lowered:
        return "ultra"
    if "rsr" in lowered:
        return "ultra"
    if re.search(r"\bpro\b", lowered):
        return "pro"
    if re.search(r"\bplus\b", lowered) or "+" in lowered:
        return "plus"
    if "mini" in lowered:
        return "mini"
    if re.search(r"(?<!oneplus\s)\bair\b", lowered):
        return "air"
    if "standard" in lowered or "标准" in lowered or "標準" in lowered:
        return "standard"
    if lowered in {"base", "regular", "normal"}:
        return "standard"
    return lowered


def _infer_variant_tier_from_name(name: str) -> str:
    lowered = normalize_competitor_name(name).lower()
    if "pro max" in lowered or "promax" in lowered:
        return "pro max"
    if "ultra" in lowered:
        return "ultra"
    if "rsr" in lowered:
        return "ultra"
    if re.search(r"\bpro\b", lowered):
        return "pro"
    if re.search(r"\bplus\b", lowered) or "+" in lowered:
        return "plus"
    if "mini" in lowered:
        return "mini"
    if re.search(r"(?<!oneplus\s)\bair\b", lowered):
        return "air"
    return "standard"


def _looks_like_tier_mismatch(
    candidate: str,
    target_product: str,
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> bool:
    target_tier = _normalized_variant_tier(_profile_value(product_profile, "variant_tier"))
    if not target_tier or target_tier == "unknown":
        target_tier = _infer_variant_tier_from_name(target_product)
    candidate_tier = _infer_variant_tier_from_name(candidate)

    if not target_tier or not candidate_tier or target_tier == "unknown" or candidate_tier == "unknown":
        return False
    return target_tier != candidate_tier


def _looks_like_non_product_phrase(name: str) -> bool:
    normalized = normalize_competitor_name(name)
    lowered = normalized.lower()
    phrase_markers = {
        "所以",
        "但是",
        "然后",
        "准备",
        "準備",
        "至于",
        "我用",
        "我想",
        "想换",
        "想換",
        "好多年",
        "推荐",
        "請問",
        "请问",
        "或者",
        "或是",
        "以及",
    }
    if any(marker in lowered for marker in phrase_markers):
        return True
    if re.search(r"[。！？!?，,；;]", normalized):
        return True
    # Long all-CJK phrases without model-like digits are usually snippets, not products.
    if len(normalized) >= 12 and not re.search(r"[A-Za-z0-9]", normalized):
        return True
    return False


def _looks_like_category_descriptor(name: str) -> bool:
    normalized = normalize_competitor_name(name)
    lowered = normalized.lower()
    compact = lowered.replace(" ", "")

    if any(marker in compact for marker in {"至于", "或者", "或是", "以及"}):
        return False
    if any(marker in compact for marker in GENERIC_DESCRIPTOR_MARKERS):
        return True
    if re.search(r"(类|類|类型|類型|品类|品類|赛道|賽道|领域|領域|方向|场景|場景)$", compact):
        return True

    matched_terms = [term for term in GENERIC_CATEGORY_TERMS if term in compact]
    if len(matched_terms) >= 2 and not re.search(r"[A-Za-z0-9]", normalized):
        return True

    return False


def _looks_like_gibberish_entity(name: str) -> bool:
    normalized = normalize_competitor_name(name)
    if not normalized:
        return True

    forbidden_chars = set("\"'`~^{}[]<>\\")
    if any(ch in forbidden_chars for ch in normalized):
        return True
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        return True

    non_space = [ch for ch in normalized if not ch.isspace()]
    if not non_space:
        return True
    symbol_count = sum(1 for ch in non_space if not ch.isalnum() and ch not in {"-", ".", "+", "&", "·", "・"})
    if symbol_count / len(non_space) > 0.2:
        return True

    scripts = {_char_script(ch) for ch in normalized if ch.isalpha()}
    scripts.discard("common")
    if len(scripts) >= 3:
        return True
    if len(scripts) == 2 and ("latin" in scripts or "cjk" in scripts):
        allowed_pairs = {frozenset({"latin", "cjk"}), frozenset({"latin", "kana"}), frozenset({"cjk", "kana"})}
        if frozenset(scripts) not in allowed_pairs:
            return True

    alnum = [ch for ch in normalized if ch.isalnum()]
    letters = [ch for ch in normalized if ch.isalpha()]
    digits = [ch for ch in normalized if ch.isdigit()]
    if len(normalized) >= 6 and alnum and len(digits) / len(alnum) > 0.45 and len(letters) >= 2:
        return True

    return False


def _char_script(ch: str) -> str:
    code = ord(ch)
    if ch.isascii():
        return "latin" if ch.isalpha() else "common"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "cjk"
    if 0x3040 <= code <= 0x30FF:
        return "kana"
    if 0xAC00 <= code <= 0xD7AF:
        return "hangul"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "unknown"
    if "LATIN" in name:
        return "latin"
    if "CJK" in name or "IDEOGRAPH" in name:
        return "cjk"
    if "HIRAGANA" in name or "KATAKANA" in name:
        return "kana"
    if "HANGUL" in name:
        return "hangul"
    if any(script in name for script in ("CYRILLIC", "ARMENIAN", "ARABIC", "HEBREW", "DEVANAGARI", "THAI", "GREEK")):
        return name.split(" ", 1)[0].lower()
    return "other"


def _has_generic_entity_signal(name: str) -> bool:
    normalized = normalize_competitor_name(name)
    if len(normalized) < 2:
        return False
    if _looks_like_gibberish_entity(normalized):
        return False
    if re.search(r"[A-Za-z0-9]", normalized):
        return True
    if re.search(r"(公司|集团|集團|科技|app|APP|App)$", normalized):
        return True
    if _looks_like_category_descriptor(normalized):
        return False
    # Short CJK names are usually brands/products once generic descriptors were excluded.
    return len(normalized) <= 12


def _descriptor_query_terms(name: str) -> list[str]:
    compact = normalize_competitor_name(name)
    compact = re.sub(r"(至于|关于|或者|或是|以及|还有|这类|类似|同类|垂直|主流|相关)", " ", compact)
    compact = re.sub(r"(类产品|类应用|类app|产品|应用|app|平台|工具|服务|赛道|领域|方向|场景)", " ", compact, flags=re.IGNORECASE)
    parts = [
        normalize_competitor_name(part)
        for part in re.split(r"[\s/／、，,;；|｜]+", compact)
    ]
    return [
        part for part in parts
        if len(part) >= 2 and part not in {"竞品", "对标", "对比", "替代"}
    ]


def _looks_like_same_series_variant(
    candidate: str,
    target_product: str,
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> bool:
    normalized_candidate = normalize_competitor_name(candidate).lower()
    normalized_target = normalize_competitor_name(target_product).lower()
    if normalized_target and normalized_target in normalized_candidate and normalized_candidate != normalized_target:
        return True

    model = _profile_value(product_profile, "model")
    if not model:
        # Capture common model tokens such as S26, 15, X200, WH-1000XM6.
        token_match = re.search(r"\b[A-Za-z]{0,4}\d[\w-]*\b", target_product)
        model = token_match.group(0) if token_match else ""
    model = normalize_competitor_name(model).lower()
    if not model or model not in normalized_candidate:
        return False

    variant_suffixes = {"ultra", "pro", "plus", "max", "mini", "air", "标准版", "高配版", "低配版"}
    return any(suffix in normalized_candidate for suffix in variant_suffixes)


def build_competitor_query(
    target_product: str,
    category: str,
    focus_dimensions: list[str],
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> str:
    subcategory = detect_subcategory(target_product, category, product_profile)
    strategy = STRATEGIES[subcategory]
    focus = " ".join(focus_dimensions[:3]) if focus_dimensions else ""
    market_category = _profile_value(product_profile, "market_category")
    market_segment = _profile_value(product_profile, "market_segment")
    profile_terms = " ".join(value for value in [market_category, market_segment] if value)
    if subcategory == "generic":
        return f"{target_product} {profile_terms} 主流竞品 替代产品 对标产品 产品名称 列表 {focus}".strip()
    return f"{target_product} {profile_terms} {' '.join(strategy.query_terms)} {focus}".strip()


def build_same_tier_query(
    target_product: str,
    category: str,
    focus_dimensions: list[str],
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> str:
    subcategory = detect_subcategory(target_product, category, product_profile)
    strategy = STRATEGIES[subcategory]
    target_tier = _normalized_variant_tier(_profile_value(product_profile, "variant_tier")) or _infer_variant_tier_from_name(target_product)
    market_category = _profile_value(product_profile, "market_category")
    market_segment = _profile_value(product_profile, "market_segment")
    focus = " ".join(focus_dimensions[:3]) if focus_dimensions else ""

    if subcategory == "smartphone":
        if target_tier == "standard":
            tier_terms = "标准款 同层级 竞品 不要 Pro Ultra Plus Max"
        else:
            tier_terms = f"{target_tier} 同层级 竞品"
        return f"{target_product} {market_category} {market_segment} {tier_terms} {' '.join(strategy.query_terms)} {focus}".strip()

    return f"{target_product} {market_category} {market_segment} 同层级 竞品 {' '.join(strategy.query_terms)} {focus}".strip()


def _candidate_keys(values: list[str]) -> set[str]:
    return {normalize_competitor_name(item).lower() for item in values if normalize_competitor_name(item)}


def _append_candidates(
    *,
    candidates: list[str],
    valid: list[str],
    dropped: list[dict[str, str]],
    added: list[str],
    target_product: str,
    strategy: ResolverStrategy,
    product_profile: ProductProfile | dict[str, Any] | None,
    competitor_count: int,
) -> None:
    for candidate in candidates:
        if len(valid) >= competitor_count:
            break
        ok, reason = _is_valid_for_strategy(candidate, target_product, strategy, product_profile)
        if not ok:
            dropped.append({"name": candidate, "reason": reason})
            continue
        if candidate.lower() in _candidate_keys(valid):
            continue
        valid.append(candidate)
        added.append(candidate)


async def resolve_competitors(
    client: SearchClient | None,
    target_product: str,
    category: str,
    focus_dimensions: list[str],
    competitor_names: list[str],
    competitor_count: int,
    product_profile: ProductProfile | dict[str, Any] | None = None,
) -> CompetitorResolution:
    """Validate competitors and supplement weak lists with strategy-specific search candidates."""
    subcategory = detect_subcategory(target_product, category, product_profile)
    strategy = STRATEGIES[subcategory]

    valid: list[str] = []
    dropped: list[dict[str, str]] = []
    descriptor_terms: list[str] = []
    for name in competitor_names:
        normalized = normalize_competitor_name(name)
        ok, reason = _is_valid_for_strategy(normalized, target_product, strategy, product_profile)
        if ok:
            valid.append(normalized)
        elif normalized:
            dropped.append({"name": normalized, "reason": reason})
            if reason in {"category_descriptor", "looks_like_non_product_phrase", "missing_product_entity_signal"}:
                descriptor_terms.extend(_descriptor_query_terms(normalized))

    valid = _dedupe_preserve_order(valid)
    query = build_competitor_query(target_product, category, focus_dimensions, product_profile)
    if descriptor_terms:
        query = f"{query} {' '.join(_dedupe_preserve_order(descriptor_terms))}".strip()
    search_queries = [query]

    added: list[str] = []
    if client is not None and len(valid) < competitor_count:
        try:
            response = await client.search(
                query=query,
                max_results=8,
                search_depth="advanced",
                include_answer=False,
            )
            search_text = "\n".join(
                f"{item.get('title', '')}\n{item.get('content') or item.get('snippet') or ''}"
                for item in response.get("results", [])
                if isinstance(item, dict)
            )
            _append_candidates(
                candidates=extract_candidate_names(search_text, strategy),
                valid=valid,
                dropped=dropped,
                added=added,
                target_product=target_product,
                strategy=strategy,
                product_profile=product_profile,
                competitor_count=competitor_count,
            )

            if len(valid) < competitor_count and subcategory == "smartphone":
                same_tier_query = build_same_tier_query(target_product, category, focus_dimensions, product_profile)
                search_queries.append(same_tier_query)
                response = await client.search(
                    query=same_tier_query,
                    max_results=8,
                    search_depth="advanced",
                    include_answer=False,
                )
                search_text = "\n".join(
                    f"{item.get('title', '')}\n{item.get('content') or item.get('snippet') or ''}"
                    for item in response.get("results", [])
                    if isinstance(item, dict)
                )
                _append_candidates(
                    candidates=extract_candidate_names(search_text, strategy),
                    valid=valid,
                    dropped=dropped,
                    added=added,
                    target_product=target_product,
                    strategy=strategy,
                    product_profile=product_profile,
                    competitor_count=competitor_count,
                )
        except Exception as exc:
            dropped.append({"name": "__resolver_search__", "reason": str(exc)[:200]})

    return CompetitorResolution(
        competitors=valid[:competitor_count],
        dropped=dropped,
        added=added,
        query=" | ".join(search_queries),
        subcategory=subcategory,
    )
