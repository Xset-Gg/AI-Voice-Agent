"""Embedding providers. One provider per deployment: vectors from different models are not
comparable, so switching EMBEDDING_PROVIDER requires re-indexing (POST /api/knowledge/reindex)."""

from abc import ABC, abstractmethod

from app.core.config import Settings, get_settings


class EmbeddingError(Exception):
    pass


class Embedder(ABC):
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]: ...


class OpenAIEmbedder(Embedder):
    def __init__(self, settings: Settings):
        from openai import AsyncOpenAI

        if not settings.openai_api_key:
            raise EmbeddingError("OPENAI_API_KEY is not configured")
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_embedding_model
        self.dimensions = settings.embedding_dimensions

    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):
            resp = await self.client.embeddings.create(
                model=self.model, input=texts[i : i + 96], dimensions=self.dimensions
            )
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out


class GeminiEmbedder(Embedder):
    def __init__(self, settings: Settings):
        from google import genai

        if not settings.gemini_api_key:
            raise EmbeddingError("GEMINI_API_KEY is not configured")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_embedding_model
        self.dimensions = settings.embedding_dimensions

    async def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        task = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        for i in range(0, len(texts), 96):
            resp = await self.client.aio.models.embed_content(
                model=self.model,
                contents=texts[i : i + 96],
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.dimensions),
            )
            out.extend(list(e.values) for e in resp.embeddings)
        return out


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        _embedder = OpenAIEmbedder(s) if s.embedding_provider == "openai" else GeminiEmbedder(s)
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Test hook / dependency override."""
    global _embedder
    _embedder = embedder
