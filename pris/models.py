from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Paper:
    title: str
    authors: list[str]
    abstract: str
    url: str
    published: str
    source: str
    source_type: str
    field: str
    doi: str = ""
    external_id: str = ""
    verified: bool = False
    verification_note: str = "尚未核验"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        stable = self.doi or self.external_id or f"{self.title}|{self.published}|{self.source}"
        return hashlib.sha256(stable.lower().encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "url": self.url,
            "published": self.published,
            "source": self.source,
            "source_type": self.source_type,
            "field": self.field,
            "doi": self.doi,
            "external_id": self.external_id,
            "verified": self.verified,
            "verification_note": self.verification_note,
        }


@dataclass(slots=True)
class Assessment:
    paper_id: str
    score: float
    one_sentence: str
    why_important: str
    research_question: str = ""
    background: str = ""
    article_structure: str = ""
    method: str = ""
    technical_core: str = ""
    main_findings: str = ""
    contribution: str = ""
    evidence: str = ""
    limitations: str = ""
    connection: str = ""
    reading_advice: str = ""
    tier: str = "quick"
