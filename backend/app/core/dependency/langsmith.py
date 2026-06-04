"""LangSmith 早启动模块。

该模块必须在任何 langchain / langgraph 模块导入之前被 import，
将 LangSmith 配置注入 os.environ，使 SDK 能在 import 时自动插桩。

安全设计：
    - 使用 os.environ.setdefault()，保证显式环境变量（Docker/k8s）优先
    - 同时设置 LANGSMITH_* 和 LANGCHAIN_* 两套变量名，兼容不同 SDK 版本
    - 未启用时零影响，仅输出一条 debug 日志
"""

import os
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def _setup_langsmith() -> None:
    """读取 Settings 中的 LangSmith 配置并注入 os.environ。

    仅在 LANGSMITH_TRACING_V2=True 且 LANGSMITH_API_KEY 非空时激活。
    """
    settings = get_settings()

    if not settings.langsmith_enabled:
        logger.debug(
            "LangSmith tracing is disabled (TRACING_V2=%s, API_KEY set=%s)",
            settings.LANGSMITH_TRACING_V2,
            bool(settings.LANGSMITH_API_KEY),
        )
        return

    # 两套前缀，覆盖 langsmith SDK 和旧版 langchain 集成
    os.environ.setdefault("LANGSMITH_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.LANGSMITH_PROJECT)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.LANGSMITH_PROJECT)

    if settings.LANGSMITH_ENDPOINT:
        os.environ.setdefault("LANGSMITH_ENDPOINT", settings.LANGSMITH_ENDPOINT)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.LANGSMITH_ENDPOINT)

    logger.info("LangSmith tracing enabled: project=%s", settings.LANGSMITH_PROJECT)


def is_langsmith_enabled() -> bool:
    """运行时查询 LangSmith 追踪是否已激活。"""
    return os.environ.get("LANGSMITH_TRACING_V2", "").lower() == "true"


# 模块导入时立即执行
_setup_langsmith()
