from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings

_settings = get_settings()


def _key(request: Request) -> str:
    # Rate-limit authenticated users per user; anonymous callers per client IP.
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_key,
    default_limits=[_settings.rate_limit_default],
    storage_uri=_settings.redis_url if _settings.environment != "test" else "memory://",
    headers_enabled=True,
    enabled=_settings.environment != "test",
)
