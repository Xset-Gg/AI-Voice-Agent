"""File storage adapter. Local disk by default; implement FileStorage for S3/GCS later."""

import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import anyio

from app.core.config import get_settings


class FileStorage(ABC):
    @abstractmethod
    async def save(self, org_id: uuid.UUID, document_id: uuid.UUID, filename: str, data: bytes) -> str: ...

    @abstractmethod
    async def load(self, path: str) -> bytes: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...


def safe_filename(name: str) -> str:
    name = Path(name).name  # strip any directory components (path traversal)
    name = re.sub(r"[^A-Za-z0-9._\- ]", "_", name).strip(" .")
    return name[:200] or "upload"


class LocalFileStorage(FileStorage):
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError("Invalid storage path")
        return full

    async def save(self, org_id, document_id, filename, data) -> str:
        rel = f"{org_id}/{document_id}/{safe_filename(filename)}"
        full = self._resolve(rel)
        await anyio.Path(full.parent).mkdir(parents=True, exist_ok=True)
        await anyio.Path(full).write_bytes(data)
        return rel

    async def load(self, path: str) -> bytes:
        return await anyio.Path(self._resolve(path)).read_bytes()

    async def delete(self, path: str) -> None:
        full = anyio.Path(self._resolve(path))
        if await full.exists():
            await full.unlink()


def get_storage() -> FileStorage:
    return LocalFileStorage(get_settings().upload_dir)
