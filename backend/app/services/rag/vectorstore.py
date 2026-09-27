"""Qdrant vector store. Every point carries org_id; every search is filtered by it (tenant isolation)."""

import asyncio
import uuid
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import get_settings


@dataclass
class VectorHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    score: float


class VectorStore:
    def __init__(self, client: AsyncQdrantClient, collection: str, dimensions: int):
        self.client = client
        self.collection = collection
        self.dimensions = dimensions
        self._ready = False
        self._lock = asyncio.Lock()

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        # Concurrent ingest jobs (and the API process) may race to create the collection.
        async with self._lock:
            if self._ready:
                return
            if not await self.client.collection_exists(self.collection):
                try:
                    await self.client.create_collection(
                        self.collection,
                        vectors_config=models.VectorParams(size=self.dimensions, distance=models.Distance.COSINE),
                    )
                except UnexpectedResponse as e:
                    if e.status_code != 409:  # 409: another process created it first
                        raise
                for field in ("org_id", "document_id"):
                    await self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
            self._ready = True

    async def upsert(
        self, org_id: uuid.UUID, document_id: uuid.UUID, items: list[tuple[uuid.UUID, list[float], bool]]
    ) -> None:
        await self.ensure_collection()
        points = [
            models.PointStruct(
                id=str(chunk_id),
                vector=vector,
                payload={"org_id": str(org_id), "document_id": str(document_id), "flagged": flagged},
            )
            for chunk_id, vector, flagged in items
        ]
        for i in range(0, len(points), 128):
            await self.client.upsert(self.collection, points=points[i : i + 128], wait=True)

    async def set_flagged(self, document_id: uuid.UUID, flagged: bool) -> None:
        await self.ensure_collection()
        await self.client.set_payload(
            self.collection,
            payload={"flagged": flagged},
            points=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))]
            ),
        )

    async def delete_document(self, document_id: uuid.UUID) -> None:
        await self.ensure_collection()
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))]
                )
            ),
            wait=True,
        )

    async def search(
        self, org_id: uuid.UUID, vector: list[float], limit: int, include_flagged: bool = False
    ) -> list[VectorHit]:
        await self.ensure_collection()
        must = [models.FieldCondition(key="org_id", match=models.MatchValue(value=str(org_id)))]
        must_not = [] if include_flagged else [
            models.FieldCondition(key="flagged", match=models.MatchValue(value=True))
        ]
        res = await self.client.query_points(
            self.collection,
            query=vector,
            query_filter=models.Filter(must=must, must_not=must_not),
            limit=limit,
            with_payload=True,
        )
        return [
            VectorHit(chunk_id=uuid.UUID(str(p.id)), document_id=uuid.UUID(p.payload["document_id"]), score=p.score)
            for p in res.points
        ]

    async def healthy(self) -> bool:
        try:
            await self.client.get_collections()
            return True
        except Exception:
            return False


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        s = get_settings()
        client = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
        _store = VectorStore(client, s.qdrant_collection, s.embedding_dimensions)
    return _store


def set_vector_store(store: VectorStore | None) -> None:
    global _store
    _store = store
