"""Document ingestion: extract → chunk → scan → embed → index."""

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log
from app.models import DocumentStatus, KnowledgeChunk, KnowledgeDocument
from app.services.rag.chunk import chunk_text
from app.services.rag.embeddings import get_embedder
from app.services.rag.extract import ExtractionError, extract_text
from app.services.rag.sanitize import scan
from app.services.rag.vectorstore import get_vector_store
from app.services.storage import get_storage


async def _document_text(doc: KnowledgeDocument) -> str:
    if doc.source_type == "file":
        data = await get_storage().load(doc.storage_path)
        return extract_text(data, doc.filename or "upload.txt")
    return doc.body or ""


async def ingest_document(db: AsyncSession, document_id: uuid.UUID) -> None:
    settings = get_settings()
    doc = await db.get(KnowledgeDocument, document_id)
    if doc is None:
        log.warning("ingest_missing_document", document_id=str(document_id))
        return

    doc.status = DocumentStatus.processing
    doc.error = None
    await db.commit()

    store = get_vector_store()
    try:
        text = await _document_text(doc)
        chunks = chunk_text(text, settings.chunk_tokens, settings.chunk_overlap_tokens)
        if not chunks:
            raise ExtractionError("Document produced no content")

        # Replace any previous chunks (re-ingestion)
        await store.delete_document(doc.id)
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))

        rows: list[KnowledgeChunk] = []
        doc_flags: list[dict] = []
        for i, c in enumerate(chunks):
            findings = scan(c.text)
            if findings:
                doc_flags.extend({**f, "chunk_index": i} for f in findings)
            rows.append(
                KnowledgeChunk(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    org_id=doc.org_id,
                    chunk_index=i,
                    text=c.text,
                    heading=c.heading,
                    token_count=c.token_count,
                    flagged=bool(findings),
                )
            )

        # Embed heading + text so section context influences retrieval.
        inputs = [f"{doc.title}\n{r.heading or ''}\n{r.text}".strip() for r in rows]
        vectors = await get_embedder().embed(inputs)
        await store.upsert(doc.org_id, doc.id, [(r.id, v, r.flagged) for r, v in zip(rows, vectors)])

        db.add_all(rows)
        doc.chunk_count = len(rows)
        doc.risk_flags = doc_flags[:50]
        doc.status = DocumentStatus.ready
        await db.commit()
        log.info("ingest_complete", document_id=str(doc.id), chunks=len(rows), flagged=len(doc_flags))
    except Exception as e:
        await db.rollback()
        doc = await db.get(KnowledgeDocument, document_id)
        if doc is not None:
            doc.status = DocumentStatus.failed
            doc.error = str(e)[:2000] if isinstance(e, ExtractionError) else f"Ingestion failed: {e}"[:2000]
            await db.commit()
        log.exception("ingest_failed", document_id=str(document_id))
