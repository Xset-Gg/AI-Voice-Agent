import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlalchemy import select, update

from app.api.deps import DB, Admin, Member, Viewer, client_ip
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.models import DocumentStatus, KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import ChunkOut, DocumentOut, FaqIn, SearchIn, SearchOut, TextDocIn
from app.services import audit, jobs
from app.services.rag.extract import SUPPORTED_EXTENSIONS
from app.services.rag.retriever import retrieve
from app.services.rag.vectorstore import get_vector_store
from app.services.storage import get_storage, safe_filename

router = APIRouter(prefix="/knowledge", tags=["knowledge base"])


async def _get(db, org_id, doc_id) -> KnowledgeDocument:
    doc = await db.get(KnowledgeDocument, doc_id)
    if doc is None or doc.org_id != org_id:
        raise NotFound("Document")
    return doc


async def _dedupe(db, org_id, sha: str) -> None:
    existing = (
        await db.execute(select(KnowledgeDocument.title).where(KnowledgeDocument.org_id == org_id, KnowledgeDocument.sha256 == sha))
    ).first()
    if existing:
        raise Conflict(f"This content was already uploaded as '{existing[0]}'")


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(principal: Viewer, db: DB):
    return (
        await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.org_id == principal.org_id).order_by(KnowledgeDocument.created_at.desc())
        )
    ).scalars().all()


@router.post("/documents/upload", response_model=DocumentOut, status_code=202)
async def upload(request: Request, principal: Member, db: DB, file: UploadFile = File(...), title: str | None = Form(None, max_length=300)):
    s = get_settings()
    filename = safe_filename(file.filename or "upload")
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise AppError(f"Unsupported file type '{ext}'", code="unsupported_file_type", status_code=415)
    max_bytes = s.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AppError(f"File exceeds {s.max_upload_mb} MB limit", code="file_too_large", status_code=413)
    if not data:
        raise AppError("File is empty", code="empty_file")
    sha = hashlib.sha256(data).hexdigest()
    await _dedupe(db, principal.org_id, sha)

    doc = KnowledgeDocument(
        id=uuid.uuid4(), org_id=principal.org_id, title=(title or Path(filename).stem)[:300], source_type="file",
        filename=filename, content_type=file.content_type, size_bytes=len(data), sha256=sha, created_by=principal.user.id,
    )
    doc.storage_path = await get_storage().save(principal.org_id, doc.id, filename, data)
    db.add(doc)
    await audit.record(db, action="knowledge.uploaded", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="document", resource_id=doc.id, data={"filename": filename, "bytes": len(data)},
                       ip_address=client_ip(request))
    await db.commit()
    await jobs.enqueue_ingest(doc.id)
    return doc


@router.post("/faqs", response_model=DocumentOut, status_code=202)
async def add_faq(request: Request, body: FaqIn, principal: Member, db: DB):
    text = f"Q: {body.question.strip()}\nA: {body.answer.strip()}"
    sha = hashlib.sha256(text.encode()).hexdigest()
    await _dedupe(db, principal.org_id, sha)
    doc = KnowledgeDocument(
        org_id=principal.org_id, title=body.question.strip()[:300], source_type="faq", body=text,
        size_bytes=len(text.encode()), sha256=sha, created_by=principal.user.id,
    )
    db.add(doc)
    await db.flush()
    await audit.record(db, action="knowledge.faq_added", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="document", resource_id=doc.id, ip_address=client_ip(request))
    await db.commit()
    await jobs.enqueue_ingest(doc.id)
    return doc


@router.post("/texts", response_model=DocumentOut, status_code=202)
async def add_text(request: Request, body: TextDocIn, principal: Member, db: DB):
    sha = hashlib.sha256(body.body.encode()).hexdigest()
    await _dedupe(db, principal.org_id, sha)
    doc = KnowledgeDocument(
        org_id=principal.org_id, title=body.title, source_type="text", body=body.body,
        size_bytes=len(body.body.encode()), sha256=sha, created_by=principal.user.id,
    )
    db.add(doc)
    await db.flush()
    await audit.record(db, action="knowledge.text_added", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="document", resource_id=doc.id, ip_address=client_ip(request))
    await db.commit()
    await jobs.enqueue_ingest(doc.id)
    return doc


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: uuid.UUID, principal: Viewer, db: DB):
    return await _get(db, principal.org_id, doc_id)


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkOut])
async def document_chunks(doc_id: uuid.UUID, principal: Viewer, db: DB):
    await _get(db, principal.org_id, doc_id)
    return (
        await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id).order_by(KnowledgeChunk.chunk_index))
    ).scalars().all()


@router.post("/documents/{doc_id}/reprocess", response_model=DocumentOut, status_code=202)
async def reprocess(doc_id: uuid.UUID, principal: Member, db: DB):
    doc = await _get(db, principal.org_id, doc_id)
    doc.status = DocumentStatus.pending
    await db.commit()
    await jobs.enqueue_ingest(doc.id)
    return doc


@router.post("/documents/{doc_id}/approve", response_model=DocumentOut)
async def approve_flagged(request: Request, doc_id: uuid.UUID, principal: Admin, db: DB):
    """An admin has reviewed the injection-scanner findings and confirms the content is safe
    to use in calls. Flagged chunks are excluded from retrieval until this happens."""
    doc = await _get(db, principal.org_id, doc_id)
    await db.execute(update(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).values(flagged=False))
    await get_vector_store().set_flagged(doc.id, False)
    await audit.record(db, action="knowledge.flags_approved", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="document", resource_id=doc.id, data={"flags": doc.risk_flags}, ip_address=client_ip(request))
    doc.risk_flags = []
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(request: Request, doc_id: uuid.UUID, principal: Member, db: DB):
    doc = await _get(db, principal.org_id, doc_id)
    await get_vector_store().delete_document(doc.id)
    if doc.storage_path:
        await get_storage().delete(doc.storage_path)
    await db.delete(doc)
    await audit.record(db, action="knowledge.deleted", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="document", resource_id=doc_id, data={"title": doc.title}, ip_address=client_ip(request))
    await db.commit()


@router.post("/search", response_model=SearchOut)
async def search(body: SearchIn, principal: Viewer, db: DB):
    """Test retrieval exactly as the voice agent would see it (flagged chunks excluded)."""
    sources = await retrieve(db, principal.org_id, body.query, top_k=body.top_k)
    return SearchOut(query=body.query, found=bool(sources), sources=sources)


@router.post("/reindex", status_code=202)
async def reindex(principal: Admin, db: DB):
    """Re-embed every document (needed after changing the embedding provider/model)."""
    docs = (await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.org_id == principal.org_id))).scalars().all()
    for d in docs:
        d.status = DocumentStatus.pending
    await db.commit()
    for d in docs:
        await jobs.enqueue_ingest(d.id)
    return {"queued": len(docs)}
