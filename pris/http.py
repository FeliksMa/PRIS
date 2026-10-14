from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


USER_AGENT = "PRIS/0.1 (personal research assistant; contact via local configuration)"


class HttpError(RuntimeError):
    pass


def _safe_url(url: str) -> str:
    """Redact credentials that some APIs embed in URL paths or queries."""
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path
    if parsed.netloc.lower() == "api.telegram.org":
        path = re.sub(r"/bot[^/]+", "/bot<redacted>", path, count=1)
    sensitive = {"key", "api_key", "token", "access_token"}
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(name, "<redacted>" if name.lower() in sensitive else value) for name, value in query]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, urllib.parse.urlencode(safe_query), ""))


def request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
) -> bytes:
    merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise HttpError(f"HTTP {exc.code} {_safe_url(url)}: {body}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"无法访问 {_safe_url(url)}: {exc.reason}") from exc


def get_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    return json.loads(request(url, headers=headers).decode("utf-8"))


def post_json(url: str, payload: Any, *, headers: dict[str, str] | None = None) -> Any:
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        merged.update(headers)
    raw = request(
        url,
        method="POST",
        headers=merged,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=90,
    )
    return json.loads(raw.decode("utf-8"))


def encode_url(base: str, params: dict[str, Any]) -> str:
    return f"{base}?{urllib.parse.urlencode(params, doseq=True)}"
