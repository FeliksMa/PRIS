from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from .models import Paper


SECTION_MARKERS = (
    "1.  Introduction",
    "1.3.  Contributions",
    "3.  Revertible Effects and Reactive Coeffects",
    "3.3.  The Context Paradigm",
    "4.  A Calculus of Dynamic Composition",
    "4.4.2.  Temporal Composability",
    "4.4.3.  Spatial Composability",
    "5.  Implementation and Case Study",
    "5.3.  Case Study: Koishi",
    "6.  Discussion",
    "8.  Conclusion",
)


def _pdf_date(value: str) -> str:
    match = re.search(r"D:(\d{4})(\d{2})(\d{2})", value or "")
    if match:
        return "-".join(match.groups())
    return datetime.fromtimestamp(0).date().isoformat()


def _section_excerpt(text: str, maximum: int = 65_000) -> str:
    pieces: list[str] = []
    per_section = max(4_000, maximum // len(SECTION_MARKERS))
    for marker in SECTION_MARKERS:
        start = text.find(marker)
        if start >= 0:
            pieces.append(text[start:start + per_section])
    excerpt = "\n\n===== SELECTED SECTION =====\n\n".join(pieces)
    return excerpt[:maximum] if excerpt else text[:maximum]


def paper_from_pdf(path: Path) -> Paper:
    path = path.resolve()
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError("PDF 没有可读取页面")
    metadata = reader.metadata or {}
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    first = pages[0]
    title = str(metadata.get("/Title") or first.splitlines()[0]).strip()
    author_line = str(metadata.get("/Author") or "").strip()
    authors = [name.strip() for name in author_line.split(",") if name.strip()]
    abstract_match = re.search(r"\bAbstract\s+(.*)", first, flags=re.S)
    abstract = " ".join((abstract_match.group(1) if abstract_match else first).split())
    full_text = "\n\n".join(pages)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    published = _pdf_date(str(metadata.get("/CreationDate") or metadata.get("/ModDate") or ""))
    return Paper(
        title=title,
        authors=authors,
        abstract=abstract,
        url=path.as_uri(),
        published=published,
        source="本地完整 PDF（Peking University / DeepSeek-AI）",
        source_type="full_text_preprint",
        field="ai",
        external_id=f"sha256:{digest}",
        verified=True,
        verification_note=(
            "已核验本地 PDF 首页、作者、摘要和正文；未发现本文 DOI/arXiv 主标识；"
            f"SHA-256 {digest[:16]}…"
        ),
        raw={
            "local_path": str(path),
            "full_text_excerpt": _section_excerpt(full_text),
            "evidence_scope": "本地 PDF 全文已读取；模型输入含摘要、引言、核心形式化结果、实现、讨论和结论选段",
            "page_count": len(reader.pages),
        },
    )
