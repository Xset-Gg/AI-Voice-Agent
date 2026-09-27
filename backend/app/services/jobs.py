"""Background job queue (arq on Redis). Ingestion runs out-of-process so uploads return fast
and a crash mid-embedding doesn't lose the job."""

import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None


async def _get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue_ingest(document_id: uuid.UUID) -> None:
    pool = await _get_pool()
    await pool.enqueue_job("ingest_document_job", str(document_id), _job_id=f"ingest:{document_id}:{uuid.uuid4().hex[:8]}")


async def enqueue_summary(call_id: uuid.UUID) -> None:
    pool = await _get_pool()
    # Deterministic job id: at most one summary per call even if /end is retried.
    await pool.enqueue_job("summarize_call_job", str(call_id), _job_id=f"summary:{call_id}", _defer_by=2)


async def enqueue_intent(call_id: uuid.UUID, segment_text: str) -> None:
    pool = await _get_pool()
    await pool.enqueue_job("classify_intent_job", str(call_id), segment_text)
