"""Real-time call event bus (Redis pub/sub) feeding the dashboard's live views."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import log

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def set_redis(client: aioredis.Redis | None) -> None:
    """Test hook."""
    global _redis
    _redis = client


def _channel(org_id: uuid.UUID | str) -> str:
    return f"calls:{org_id}"


def _default(o):
    if isinstance(o, (uuid.UUID,)):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o)}")


async def publish(org_id: uuid.UUID, call_id: uuid.UUID, event_type: str, data: dict) -> None:
    message = json.dumps({"call_id": call_id, "type": event_type, "data": data}, default=_default)
    try:
        await get_redis().publish(_channel(org_id), message)
    except Exception as e:  # live view is best-effort; persistence already happened
        log.warning("event_publish_failed", error=str(e))


async def subscribe(org_id: uuid.UUID) -> AsyncIterator[str]:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(_channel(org_id))
    try:
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                yield msg["data"]
    finally:
        await pubsub.unsubscribe(_channel(org_id))
        await pubsub.aclose()
