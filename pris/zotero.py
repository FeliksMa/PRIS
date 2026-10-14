from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .config import Settings
from .http import get_json, post_json
from .models import Paper


class ZoteroClient:
    def __init__(self, settings: Settings):
        self.api_key = settings.secret("ZOTERO_API_KEY")
        self.user_id = settings.secret("ZOTERO_USER_ID")
        self.enabled = bool(settings.raw.get("zotero", {}).get("enabled", True))
        self.collection_name = settings.raw.get("zotero", {}).get("collection_name", "PRIS 深度阅读")
        self.base = f"https://api.zotero.org/users/{self.user_id}"

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.api_key and self.user_id)

    @property
    def headers(self) -> dict[str, str]:
        return {"Zotero-API-Key": self.api_key, "Zotero-API-Version": "3"}

    def _get_collection(self) -> str:
        collections = get_json(f"{self.base}/collections?limit=100", headers=self.headers)
        for item in collections:
            if item.get("data", {}).get("name") == self.collection_name:
                return item["key"]
        result = post_json(
            f"{self.base}/collections",
            [{"name": self.collection_name, "parentCollection": False}],
            headers=self.headers,
        )
        successful = result.get("successful", {})
        created = successful.get("0") or successful.get(0)
        if not created:
            raise RuntimeError(f"无法创建 Zotero 集合：{result}")
        return created["key"]

    def _exists(self, paper: Paper) -> bool:
        query = urllib.parse.quote(paper.doi or paper.title, safe="")
        rows = get_json(f"{self.base}/items/top?q={query}&limit=20", headers=self.headers)
        target = (paper.doi or "").lower()
        for row in rows:
            data = row.get("data", {})
            if target and data.get("DOI", "").lower() == target:
                return True
            if data.get("title", "").strip().lower() == paper.title.strip().lower():
                return True
        return False

    @staticmethod
    def _creator(name: str) -> dict[str, str]:
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            return {"creatorType": "author", "firstName": parts[0], "lastName": parts[1]}
        return {"creatorType": "author", "name": name}

    def add(self, paper: Paper) -> bool:
        if not self.ready:
            return False
        if self._exists(paper):
            return True
        collection = self._get_collection()
        item_type = "journalArticle" if paper.doi else "report"
        item: dict[str, Any] = {
            "itemType": item_type,
            "title": paper.title,
            "creators": [self._creator(name) for name in paper.authors],
            "abstractNote": paper.abstract,
            "date": paper.published,
            "url": paper.url,
            "collections": [collection],
            "tags": [{"tag": "PRIS"}, {"tag": "待获取全文"}],
            "relations": {},
        }
        if item_type == "journalArticle":
            item["DOI"] = paper.doi
            item["publicationTitle"] = paper.source
        else:
            item["institution"] = paper.source
            item["reportNumber"] = paper.external_id
        result = post_json(f"{self.base}/items", [item], headers=self.headers)
        return bool(result.get("successful"))
