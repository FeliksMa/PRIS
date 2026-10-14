"""Fail-closed guards for cloud research exports; never print matching secrets."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit, parse_qsl


def is_sensitive_name(name: str) -> bool:
    upper = name.upper()
    return upper.endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET")) or upper in {
        "KEY", "API_KEY", "TOKEN", "ACCESS_TOKEN", "PASSWORD", "SECRET", "SIGNATURE", "AUTHORIZATION",
        "TELEGRAM_CHAT_ID", "ZOTERO_USER_ID"
    }


def private_values() -> list[str]:
    return [v for k, v in os.environ.items() if is_sensitive_name(k) and len(v) >= 5]


def research_export(value, credentials: list[str] | None = None):
    """Block credential exports and strip machine paths, retaining research text."""
    credentials = private_values() if credentials is None else credentials
    def clean(item):
        if isinstance(item, dict):
            if any(is_sensitive_name(str(k)) for k in item):
                raise ValueError("云端资料含敏感配置字段，已阻止上传")
            return {k: clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            if any(secret in item for secret in credentials):
                raise ValueError("云端资料含凭据或账号标识，已阻止上传；请在本地检查，不要粘贴密钥")
            item = re.sub(r"file://[^\s)\]<>]+", "[本地文件路径已隐藏]", item, flags=re.I)
            item = re.sub(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\r\n)\]<>\"|]+", "[本地文件路径已隐藏]", item)
            return item
        return item
    return clean(value)


def public_paper_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        if any(is_sensitive_name(k) for k, _ in parse_qsl(parsed.query)):
            return ""
        return url
    except ValueError:
        return ""
