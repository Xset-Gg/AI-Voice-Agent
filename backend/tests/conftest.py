import hashlib
import math
import os
import re
import tempfile

_tmp = tempfile.mkdtemp(prefix="voice-agent-tests-")
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp}/test.db",
    JWT_SECRET="test-secret-" + "x" * 40,
    ENCRYPTION_KEY="ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
    INTERNAL_API_TOKEN="internal-test-token-123456789",
    UPLOAD_DIR=f"{_tmp}/uploads",
    PUBLIC_BASE_URL="https://voice.example.com",
    TWILIO_ACCOUNT_SID="AC" + "0" * 32,
    TWILIO_AUTH_TOKEN="twilio-test-auth-token",
    LIVEKIT_SIP_HOST="test.sip.livekit.cloud",
    EMBEDDING_DIMENSIONS="256",
    RETRIEVAL_MIN_SCORE="0.2",
    OPENAI_API_KEY="",
    GEMINI_API_KEY="",
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import events, jobs  # noqa: E402
from app.services.rag import embeddings, vectorstore  # noqa: E402
from app.services.rag.embeddings import Embedder  # noqa: E402


class HashingEmbedder(Embedder):
    """Deterministic local embedder for tests: hashed bag of words + bigrams, L2-normalised.
    Texts sharing vocabulary get high cosine similarity, which is enough to test retrieval logic."""

    dimensions = 256

    async def embed(self, texts, *, is_query=False):
        out = []
        for t in texts:
            words = re.findall(r"[a-z0-9]+", t.lower())
            feats = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
            v = [0.0] * self.dimensions
            for f in feats:
                v[int(hashlib.md5(f.encode()).hexdigest(), 16) % self.dimensions] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class RecordingBus:
    def __init__(self):
        self.messages = []

    async def publish(self, channel, message):
        self.messages.append((channel, message))

    async def ping(self):
        return True


@pytest_asyncio.fixture(autouse=True)
async def _env(monkeypatch):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    embeddings.set_embedder(HashingEmbedder())
    store = vectorstore.VectorStore(AsyncQdrantClient(location=":memory:"), "test_chunks", 256)
    vectorstore.set_vector_store(store)
    bus = RecordingBus()
    events.set_redis(bus)

    # Run background jobs inline so tests observe their effects.
    from app.services.rag.ingest import ingest_document

    async def inline_ingest(document_id):
        async with SessionLocal() as db:
            await ingest_document(db, document_id)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(jobs, "enqueue_ingest", inline_ingest)
    monkeypatch.setattr(jobs, "enqueue_intent", noop)
    monkeypatch.setattr(jobs, "enqueue_summary", noop)
    yield bus
    embeddings.set_embedder(None)
    vectorstore.set_vector_store(None)
    events.set_redis(None)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


async def register(client, email="owner@acme-example.com", org="Acme Plumbing", password="supersecret123"):
    r = await client.post("/api/auth/register", json={
        "organization_name": org, "full_name": "Owner", "email": email, "password": password, "timezone": "UTC",
    })
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def internal_headers():
    return {"Authorization": "Bearer internal-test-token-123456789"}
