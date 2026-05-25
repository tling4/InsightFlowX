from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session():
    """FastAPI 依赖注入：为每个请求提供独立的数据库 session。"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
