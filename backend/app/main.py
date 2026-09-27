import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.routes import agents, auth, calls, internal, knowledge, phone_numbers, scheduling, twilio
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, log
from app.core.rate_limit import limiter
from app.db.session import SessionLocal
from app.services.events import get_redis
from app.services.rag.vectorstore import get_vector_store

settings = get_settings()
configure_logging(settings.log_level, json_logs=settings.is_production)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("api_starting", environment=settings.environment)
    yield
    log.info("api_stopping")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "AI voice agent platform API. Authenticate with `POST /api/auth/login` and send the token as "
        "`Authorization: Bearer <token>`. Real-time call events stream over `WS /api/calls/live?token=`."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter
register_error_handlers(app)


@app.exception_handler(RateLimitExceeded)
async def rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"error": {"code": "rate_limited", "message": f"Too many requests: {exc.detail}",
                   "request_id": getattr(request.state, "request_id", None)}},
        status_code=429,
    )


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    if len(request_id) > 64:
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if not request.url.path.startswith(("/health", "/metrics")):
        log.info("request", method=request.method, path=request.url.path, status=response.status_code,
                 ms=round(elapsed, 1), request_id=request_id)
    return response


api = APIRouter(prefix="/api")
for module in (auth, agents, phone_numbers, calls, knowledge, scheduling, twilio, internal):
    api.include_router(module.router)
api.include_router(agents.tools_router)
app.include_router(api)

Instrumentator(excluded_handlers=["/health", "/ready", "/metrics"]).instrument(app).expose(app, include_in_schema=False)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    """Readiness: dependencies reachable."""
    checks = {}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e.__class__.__name__}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e.__class__.__name__}"
    checks["qdrant"] = "ok" if await get_vector_store().healthy() else "error"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)
