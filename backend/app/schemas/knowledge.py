import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import DocumentStatus
from app.schemas.common import ORM


class DocumentOut(ORM):
    id: uuid.UUID
    title: str
    source_type: str
    filename: str | None
    content_type: str | None
    size_bytes: int
    status: DocumentStatus
    error: str | None
    chunk_count: int
    risk_flags: list
    created_at: datetime
    updated_at: datetime


class FaqIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    answer: str = Field(min_length=1, max_length=8000)


class TextDocIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=500_000)


class ChunkOut(ORM):
    id: uuid.UUID
    chunk_index: int
    heading: str | None
    text: str
    token_count: int
    flagged: bool


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    heading: str | None
    text: str
    score: float
    flagged: bool


class SearchOut(BaseModel):
    query: str
    found: bool
    sources: list[SourceOut]
