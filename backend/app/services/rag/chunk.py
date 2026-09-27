"""Heading-aware, token-bounded chunking with overlap."""

import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class Chunk:
    text: str
    heading: str | None
    token_count: int


@lru_cache
def _enc():
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc().encode(text, disallowed_special=()))


def _sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        m = HEADING_RE.match(line.strip())
        if m:
            sections.append((m.group(2).strip()[:300], []))
        else:
            sections[-1][1].append(line)
    return [(h, "\n".join(lines).strip()) for h, lines in sections if "\n".join(lines).strip()]


def _split_long(paragraph: str, max_tokens: int) -> list[str]:
    """Split an oversized paragraph on sentence boundaries, then hard-split by tokens."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    out, buf = [], ""
    for s in sentences:
        candidate = f"{buf} {s}".strip()
        if count_tokens(candidate) <= max_tokens:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        if count_tokens(s) <= max_tokens:
            buf = s
        else:
            toks = _enc().encode(s, disallowed_special=())
            for i in range(0, len(toks), max_tokens):
                out.append(_enc().decode(toks[i : i + max_tokens]))
            buf = ""
    if buf:
        out.append(buf)
    return out


def chunk_text(text: str, max_tokens: int = 400, overlap_tokens: int = 60) -> list[Chunk]:
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap must be smaller than chunk size")
    chunks: list[Chunk] = []
    for heading, body in _sections(text):
        paragraphs: list[str] = []
        for p in re.split(r"\n\s*\n", body):
            p = p.strip()
            if not p:
                continue
            paragraphs.extend(_split_long(p, max_tokens) if count_tokens(p) > max_tokens else [p])

        current: list[str] = []
        current_tokens = 0
        for p in paragraphs:
            pt = count_tokens(p)
            if current and current_tokens + pt > max_tokens:
                chunks.append(_make(current, heading))
                # carry trailing paragraphs forward as overlap
                overlap: list[str] = []
                ot = 0
                for prev in reversed(current):
                    t = count_tokens(prev)
                    if ot + t > overlap_tokens:
                        break
                    overlap.insert(0, prev)
                    ot += t
                current, current_tokens = overlap, ot
            current.append(p)
            current_tokens += pt
        if current:
            chunks.append(_make(current, heading))
    return chunks


def _make(paragraphs: list[str], heading: str | None) -> Chunk:
    body = "\n\n".join(paragraphs)
    return Chunk(text=body, heading=heading, token_count=count_tokens(body))
