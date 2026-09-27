"""Text extraction for uploaded knowledge files."""

import csv
import io
import json
from pathlib import Path

from bs4 import BeautifulSoup

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".html", ".htm", ".json"}


class ExtractionError(Exception):
    pass


def extract_text(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    try:
        if ext == ".pdf":
            text = _pdf(data)
        elif ext == ".docx":
            text = _docx(data)
        elif ext in (".html", ".htm"):
            text = _html(data)
        elif ext == ".csv":
            text = _csv(data)
        elif ext == ".json":
            text = json.dumps(json.loads(_decode(data)), indent=2, ensure_ascii=False)
        else:
            text = _decode(data)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"Could not read {ext} file: {e}") from e
    text = _normalize(text)
    if not text.strip():
        raise ExtractionError("No extractable text found (scanned PDFs need OCR before upload)")
    return text


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Unable to decode text file")


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise ExtractionError("PDF is password protected") from e
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def _docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    for para in document.paragraphs:
        style = (para.style.name or "").lower() if para.style is not None else ""
        text = para.text.strip()
        if not text:
            continue
        if style.startswith("heading"):
            level = "".join(c for c in style if c.isdigit()) or "1"
            lines.append(f"{'#' * min(int(level), 6)} {text}")
        else:
            lines.append(text)
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n\n".join(lines)


def _html(data: bytes) -> str:
    soup = BeautifulSoup(_decode(data), "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "iframe"]):
        tag.decompose()
    # Hidden elements are a common prompt-injection vector — drop them.
    for tag in soup.select('[hidden], [style*="display:none"], [style*="display: none"], [aria-hidden="true"]'):
        tag.decompose()
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            h.replace_with(f"\n{'#' * level} {h.get_text(strip=True)}\n")
    return soup.get_text("\n")


def _csv(data: bytes) -> str:
    reader = csv.reader(io.StringIO(_decode(data)))
    rows = list(reader)
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    out = []
    for row in body:
        out.append("; ".join(f"{h.strip()}: {v.strip()}" for h, v in zip(header, row) if v.strip()))
    return "\n".join(out)


def _normalize(text: str) -> str:
    # Strip control chars (except newline/tab) and zero-width characters used to hide text.
    zero_width = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)
    text = text.translate(zero_width)
    text = "".join(c for c in text if c in "\n\t" or c.isprintable())
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blank = 0
    for ln in lines:
        blank = blank + 1 if not ln.strip() else 0
        if blank <= 1:
            out.append(ln)
    return "\n".join(out).strip()
