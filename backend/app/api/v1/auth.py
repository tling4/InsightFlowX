from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.schemas.auth import UserRegister, UserLogin, UserResponse, TokenResponse
from app.db.queries.user_queries import get_user_by_email, get_user_by_username
from app.services.auth_service import create_user, authenticate_user, create_access_token
from app.services.rate_limiter import login_rate_limit, register_rate_limit
from app.exceptions import DuplicateResourceError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_async_session), _rate: None = Depends(register_rate_limit)):
    existing_email = await get_user_by_email(db, data.email)
    if existing_email:
        raise DuplicateResourceError("邮箱", data.email)
    existing_username = await get_user_by_username(db, data.username)
    if existing_username:
        raise DuplicateResourceError("用户名", data.username)
    user = await create_user(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_async_session), _rate: None = Depends(login_rate_limit)):
    user = await authenticate_user(db, data.email, data.password)
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user
