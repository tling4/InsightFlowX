import time
import asyncio
from collections import defaultdict
from fastapi import Request, HTTPException


class RateLimiter:
    """简单的内存固定窗口速率限制器。

    在单个 asyncio 事件循环中线程安全。
    跟踪每个键（IP）在可配置时间窗口内的请求。
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            window_start, count = self._windows.get(key, (0, 0))
            if now - window_start > self.window_seconds:
                self._windows[key] = (now, 1)
                return True
            if count >= self.max_requests:
                return False
            self._windows[key] = (window_start, count + 1)
            return True


_login_limiter = RateLimiter(max_requests=10, window_seconds=60)
_register_limiter = RateLimiter(max_requests=5, window_seconds=60)


async def login_rate_limit(request: Request):
    key = request.client.host if request.client else "unknown"
    if not await _login_limiter.is_allowed(key):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")


async def register_rate_limit(request: Request):
    key = request.client.host if request.client else "unknown"
    if not await _register_limiter.is_allowed(key):
        raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")
