from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .http import encode_url, get_json, request
from .models import Paper


ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: str) -> str:
    value = html.unescape(TAG_RE.sub(" ", value or ""))
    return " ".join(value.split())


def is_recent(value: str, max_age_days: int) -> bool:
    if not value:
        return True
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        pass
    if parsed is None:
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%B %Y"):
                try:
                    parsed = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


def collect_rss(source: dict[str, Any]) -> list[Paper]:
    if source.get("enabled", True) is False:
        return []
    root = ET.fromstring(request(source["url"]))
    papers: list[Paper] = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title", ""))
        link = clean_text(item.findtext("link", ""))
        description = clean_text(item.findtext("description", ""))
        published = clean_text(item.findtext("pubDate", ""))
        guid = clean_text(item.findtext("guid", ""))
        doi_match = DOI_RE.search(" ".join((link, guid, description)))
        papers.append(Paper(
            title=title,
            authors=[],
            abstract=description,
            url=link,
            published=published,
            source=source["name"],
            source_type=source.get("source_type", "feed_item"),
            field=source.get("field", "economics"),
            doi=doi_match.group(0).rstrip(".,)") if doi_match else "",
            external_id=guid or link,
            raw={"region": source.get("region", "global")},
        ))
    if not papers:
        namespace_match = re.match(r"\{([^}]+)\}", root.tag)
        ns = {"atom": namespace_match.group(1)} if namespace_match else ARXIV_NS
        for entry in root.findall(".//atom:entry", ns):
            links = entry.findall("atom:link", ns)
            link = next((node.get("href", "") for node in links if node.get("rel", "alternate") == "alternate"), "")
            entry_id = clean_text(entry.findtext("atom:id", "", ns))
            summary = clean_text(entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns))
            doi_match = DOI_RE.search(" ".join((link, entry_id, summary)))
            papers.append(Paper(
                title=clean_text(entry.findtext("atom:title", "", ns)),
                authors=[clean_text(node.findtext("atom:name", "", ns)) for node in entry.findall("atom:author", ns)],
                abstract=summary,
                url=link or entry_id,
                published=clean_text(entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns)),
                source=source["name"],
                source_type=source.get("source_type", "feed_item"),
                field=source.get("field", "economics"),
                doi=doi_match.group(0).rstrip(".,)") if doi_match else "",
                external_id=entry_id or link,
                raw={"region": source.get("region", "global")},
            ))
    max_age_days = int(source.get("max_age_days", 7))
    return [p for p in papers if p.title and p.url and is_recent(p.published, max_age_days)]


def collect_arxiv(config: dict[str, Any], interests: list[str]) -> list[Paper]:
    if not config.get("enabled", True):
        return []
    categories = config.get("categories", ["cs.AI", "cs.LG"])
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    keyword_query = " OR ".join(f'all:"{word}"' for word in interests[:12])
    search_query = f"({category_query}) AND ({keyword_query})" if keyword_query else f"({category_query})"
    url = encode_url("https://export.arxiv.org/api/query", {
        "search_query": search_query,
        "start": 0,
        "max_results": int(config.get("max_results", 30)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    root = ET.fromstring(request(url))
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        entry_id = clean_text(entry.findtext("atom:id", "", ARXIV_NS))
        arxiv_id = entry_id.rstrip("/").split("/")[-1]
        doi = clean_text(entry.findtext("arxiv:doi", "", ARXIV_NS))
        authors = [clean_text(author.findtext("atom:name", "", ARXIV_NS)) for author in entry.findall("atom:author", ARXIV_NS)]
        papers.append(Paper(
            title=clean_text(entry.findtext("atom:title", "", ARXIV_NS)),
            authors=[a for a in authors if a],
            abstract=clean_text(entry.findtext("atom:summary", "", ARXIV_NS)),
            url=entry_id,
            published=clean_text(entry.findtext("atom:published", "", ARXIV_NS)),
            source="arXiv",
            source_type="preprint",
            field="ai",
            doi=doi,
            external_id=f"arXiv:{arxiv_id}",
            verified=True,
            verification_note=f"已通过 arXiv 官方记录核验：{arxiv_id}",
        ))
    return papers


def _crossref_date(item: dict[str, Any]) -> str:
    for key in ("published-online", "published-print", "published", "created"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            values = parts[0] + [1, 1]
            return f"{values[0]:04d}-{values[1]:02d}-{values[2]:02d}"
    return ""


def collect_crossref_journal(journal: dict[str, Any], days_back: int = 3) -> list[Paper]:
    since = (date.today() - timedelta(days=days_back)).isoformat()
    issn = urllib.parse.quote(journal["issn"], safe="")
    url = encode_url(f"https://api.crossref.org/journals/{issn}/works", {
        "filter": f"from-pub-date:{since}",
        "sort": "published",
        "order": "desc",
        "rows": 20,
        "select": "DOI,title,author,abstract,URL,published,published-online,published-print,created,type",
    })
    data = get_json(url)
    papers: list[Paper] = []
    for item in data.get("message", {}).get("items", []):
        authors = [
            " ".join(filter(None, (a.get("given", ""), a.get("family", ""))))
            for a in item.get("author", [])
        ]
        doi = item.get("DOI", "")
        papers.append(Paper(
            title=clean_text((item.get("title") or [""])[0]),
            authors=[a for a in authors if a],
            abstract=clean_text(item.get("abstract", "")),
            url=item.get("URL", f"https://doi.org/{doi}" if doi else ""),
            published=_crossref_date(item),
            source=journal["name"],
            source_type="peer_reviewed",
            field="economics",
            doi=doi,
            external_id=doi,
        ))
    return [p for p in papers if p.title and p.doi]


def collect_nber(config: dict[str, Any]) -> list[Paper]:
    """Use the public search endpoint referenced by NBER's current papers page."""
    if not config.get("enabled", True):
        return []
    url = encode_url(
        "https://www.nber.org/api/v1/working_page_listing/contentType/working_paper/_/_/search",
        {"page": 1, "perPage": int(config.get("max_results", 30)), "sortBy": "public_date"},
    )
    data = get_json(url)
    papers: list[Paper] = []
    rows = data.get("results", [])
    new_rows = [item for item in rows if item.get("newthisweek")]
    if new_rows:
        rows = new_rows
    for item in rows[:int(config.get("max_results", 30))]:
        relative_url = item.get("url", "")
        match = re.search(r"/(w\d+)$", relative_url)
        number = match.group(1) if match else ""
        doi = f"10.3386/{number}" if number else ""
        authors = [clean_text(author) for author in item.get("authors", [])]
        papers.append(Paper(
            title=clean_text(item.get("title", "")),
            authors=[author for author in authors if author],
            abstract=clean_text(item.get("abstract", "")),
            url=f"https://www.nber.org{relative_url}" if relative_url.startswith("/") else relative_url,
            published=clean_text(item.get("displaydate", "")),
            source="NBER Working Papers",
            source_type="working_paper",
            field="economics",
            doi=doi,
            external_id=number,
            raw={"new_this_week": bool(item.get("newthisweek")), "region": "global"},
        ))
    return [paper for paper in papers if paper.title and paper.external_id]


def collect_all(config: dict[str, Any]) -> tuple[list[Paper], list[str]]:
    sources = config.get("sources", {})
    errors: list[str] = []
    papers: list[Paper] = []
    profile = config.get("profile", {})
    ai_interests = profile.get("interests", {}).get("ai", [])

    jobs: list[tuple[str, Any]] = []
    for journal in sources.get("crossref_journals", []):
        jobs.append((journal["name"], lambda journal=journal: collect_crossref_journal(
            journal, int(config["system"].get("days_back", 3))
        )))
    for feed in sources.get("rss", []):
        jobs.append((feed["name"], lambda feed=feed: collect_rss(feed)))
    if sources.get("nber", {}).get("enabled", True):
        jobs.append(("NBER Working Papers", lambda: collect_nber(sources.get("nber", {}))))
    if sources.get("arxiv", {}).get("enabled", True):
        jobs.append(("arXiv", lambda: collect_arxiv(sources["arxiv"], ai_interests)))

    for name, job in jobs:
        try:
            papers.extend(job())
        except Exception as exc:  # 单个来源失败不能中断整份日报
            errors.append(f"{name}: {exc}")

    deduped: dict[str, Paper] = {}
    for paper in papers:
        deduped.setdefault(paper.id, paper)
    return list(deduped.values()), errors
