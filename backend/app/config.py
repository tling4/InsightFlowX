from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


BACKEND_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """应用配置，从 .env 文件加载。"""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dagents"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/dagents"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.3

    TAVILY_API_KEY: str = ""

    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "dagents-insightflow"
    LANGSMITH_TRACING_V2: bool = False
    LANGSMITH_ENDPOINT: str = ""

    @property
    def langsmith_enabled(self) -> bool:
        """便捷判断：是否已启用 LangSmith 追踪。"""
        return self.LANGSMITH_TRACING_V2 and bool(self.LANGSMITH_API_KEY)

    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
