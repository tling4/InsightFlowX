import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.db.queries.user_queries import get_user_by_id
from app.services.auth_service import decode_access_token
from app.exceptions import InvalidTokenError
from app.db.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """从 JWT token 解析当前用户。

    链路：Bearer token → decode → sub(uuid) → DB 查询 → 返回 User
    任何环节失败均抛出 InvalidTokenError，由全局异常处理器统一响应。
    """
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise InvalidTokenError("无效或过期的令牌")
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise InvalidTokenError("令牌缺少用户信息")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise InvalidTokenError("令牌格式错误")
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise InvalidTokenError("用户不存在或已禁用")
    return user
