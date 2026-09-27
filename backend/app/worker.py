"""arq worker: `arq app.worker.WorkerSettings`"""

import uuid

from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, log
from app.db.session import SessionLocal
from app.models import Call, CallOutcome, TranscriptSegment
from app.services.calls import add_event
from app.services.intent import classify, summarize
from app.services.rag.ingest import ingest_document


async def ingest_document_job(ctx, document_id: str) -> None:
    async with SessionLocal() as db:
        await ingest_document(db, uuid.UUID(document_id))


async def classify_intent_job(ctx, call_id: str, text: str) -> None:
    async with SessionLocal() as db:
        call = await db.get(Call, uuid.UUID(call_id))
        if call is None:
            return
        recent = (
            await db.execute(
                select(TranscriptSegment.role, TranscriptSegment.text)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.sequence.desc())
                .limit(6)
            )
        ).all()
        context = [f"{r}: {t}" for r, t in reversed(recent)]
        result = await classify(text, context)
        if not result:
            return
        call.intent = result["intent"]
        await add_event(db, call, "intent", {**result, "utterance": text[:300]})


async def summarize_call_job(ctx, call_id: str) -> None:
    async with SessionLocal() as db:
        call = await db.get(Call, uuid.UUID(call_id))
        if call is None:
            return
        rows = (
            await db.execute(
                select(TranscriptSegment.role, TranscriptSegment.text)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.sequence)
            )
        ).all()
        if not rows:
            return
        transcript = "\n".join(f"{'Caller' if r == 'user' else 'Assistant'}: {t}" for r, t in rows)[-12000:]
        result = await summarize(transcript)
        if not result:
            return
        # Outbound calls store their purpose in summary; keep it as a prefix.
        call.summary = (f"{call.summary} — " if call.summary and call.direction.value == "outbound" else "") + result["summary"]
        if call.outcome in (None, CallOutcome.unresolved) and result["resolved"]:
            call.outcome = CallOutcome.resolved
        await add_event(db, call, "summary", result)


async def startup(ctx):
    s = get_settings()
    configure_logging(s.log_level, json_logs=s.is_production)
    log.info("worker_started")


class WorkerSettings:
    functions = [ingest_document_job, classify_intent_job, summarize_call_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 600
    max_tries = 3
