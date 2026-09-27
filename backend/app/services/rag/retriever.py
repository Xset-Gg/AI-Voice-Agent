import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import DocumentStatus, KnowledgeChunk, KnowledgeDocument
from app.services.rag.embeddings import get_embedder
from app.services.rag.vectorstore import get_vector_store


async def retrieve(
    db: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
    include_flagged: bool = False,
) -> list[dict]:
    """Semantic search scoped to one organization. Returns only sufficiently relevant chunks
    from documents that are ready; an empty list means 'not in the knowledge base'."""
    s = get_settings()
    top_k = top_k or s.retrieval_top_k
    min_score = s.retrieval_min_score if min_score is None else min_score

    [vector] = await get_embedder().embed([query], is_query=True)
    hits = await get_vector_store().search(org_id, vector, limit=top_k, include_flagged=include_flagged)
    hits = [h for h in hits if h.score >= min_score]
    if not hits:
        return []

    rows = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeChunk.id.in_([h.chunk_id for h in hits]),
                KnowledgeChunk.org_id == org_id,  # defence in depth on top of the vector filter
                KnowledgeDocument.status == DocumentStatus.ready,
            )
        )
    ).all()
    by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}

    sources = []
    for h in hits:
        if h.chunk_id not in by_id:
            continue
        chunk, doc = by_id[h.chunk_id]
        if chunk.flagged and not include_flagged:
            continue
        sources.append(
            {
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "heading": chunk.heading,
                "text": chunk.text,
                "score": round(h.score, 4),
                "flagged": chunk.flagged,
            }
        )
    return sources
