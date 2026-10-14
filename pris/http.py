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
    sensitive = {"key", "api_key", "token", "access_token", "secret", "password", "signature", "authorization"}
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(name, "<redacted>" if name.lower() in sensitive else value) for name, value in query]
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urllib.parse.urlunsplit((parsed.scheme, host, path, urllib.parse.urlencode(safe_query), ""))


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward authentication to a redirect destination, even on the same host.
        return None


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
    authenticated = any(name.lower() in {
        "authorization", "zotero-api-key", "oai-sites-authorization", "x-pris-runner-token"
    } for name in merged) or urllib.parse.urlsplit(url).hostname == "api.telegram.org"
    if authenticated and urllib.parse.urlsplit(url).scheme != "https":
        raise HttpError("带凭据的请求必须使用 HTTPS")
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    opener = urllib.request.build_opener(_NoCredentialRedirect()) if authenticated else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        exc.close()
        # Providers may echo keys or submitted research in response bodies.
        raise HttpError(f"HTTP {exc.code} {_safe_url(url)}") from None
    except urllib.error.URLError as exc:
        raise HttpError(f"无法访问 {_safe_url(url)}（网络或 TLS 连接失败）") from None


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
