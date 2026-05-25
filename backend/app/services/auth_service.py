import uuid
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.db.models.user import User
from app.db.queries.user_queries import get_user_by_email, get_user_by_username, get_user_by_id
from app.exceptions import InvalidCredentialsError
from app.schemas.auth import UserRegister

settings = get_settings()


def hash_password(password: str) -> str:
    """bcrypt 加密密码。"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文与 bcrypt 哈希是否匹配。"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID) -> str:
    """签发 JWT access_token，payload 包含 sub=user_id + exp。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """解码 JWT token，失败返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


async def create_user(db: AsyncSession, data: UserRegister) -> User:
    user = User(
        id=uuid.uuid4(),
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        display_name=data.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError()
    return user
