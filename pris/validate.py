from __future__ import annotations

import re
import urllib.parse
from difflib import SequenceMatcher

from .http import get_json
from .models import Paper


DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)


def normalize_doi(value: str) -> str:
    return DOI_PREFIX.sub("", (value or "").strip()).rstrip(".,;) ").lower()


def normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.lower()).split())


def validate_paper(paper: Paper) -> Paper:
    paper.doi = normalize_doi(paper.doi)
    if not paper.doi:
        if paper.external_id.startswith("arXiv:") and "arxiv.org" in paper.url:
            paper.verified = True
            paper.verification_note = f"无 DOI；已通过主标识 {paper.external_id} 核验"
        else:
            paper.verified = bool(paper.external_id and paper.url)
            paper.verification_note = "无 DOI；仅核验了原始来源标识" if paper.verified else "缺少可核验主标识"
        return paper

    encoded = urllib.parse.quote(paper.doi, safe="")
    try:
        record = get_json(f"https://api.crossref.org/works/{encoded}").get("message", {})
    except Exception as exc:
        paper.verified = False
        paper.verification_note = f"DOI 暂时无法通过 Crossref 核验：{exc}"
        return paper
    official_title = (record.get("title") or [""])[0]
    similarity = SequenceMatcher(None, normalize_title(paper.title), normalize_title(official_title)).ratio()
    if similarity < 0.78:
        paper.verified = False
        paper.verification_note = f"DOI 存在，但标题不匹配（相似度 {similarity:.0%}）"
        return paper
    paper.verified = True
    paper.title = official_title or paper.title
    paper.url = f"https://doi.org/{paper.doi}"
    paper.verification_note = "DOI、标题已通过 Crossref 核验"
    return paper

