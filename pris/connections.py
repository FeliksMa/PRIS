"""Local connection settings; browser responses never include credential values."""
from __future__ import annotations

import base64
import ctypes
import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

SECRET_NAMES = ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ZOTERO_API_KEY", "ZOTERO_USER_ID")
LOCK = threading.RLock()


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ValueError("此系统暂不支持网页加密保存凭据；请使用本机 .env 或环境变量")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    call = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    call.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    call.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # Current-user protection only; never use CRYPTPROTECT_LOCAL_MACHINE.
    if not call(ctypes.byref(source), None, None, None, None, 4, ctypes.byref(target)):
        raise ValueError("Windows 凭据保护失败；未改用明文保存，请确认当前系统账号")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def read_store(root: Path) -> dict:
    path = root / "data" / "connections.json"
    if not path.exists():
        return {"options": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("options"), dict):
            raise ValueError()
        return value
    except (ValueError, OSError):
        raise ValueError("本机连接配置无法读取；请检查 data/connections.json，不要粘贴其中内容") from None


def protected_values(store: dict) -> dict[str, str]:
    if not store.get("protected_credentials"):
        return {}
    try:
        result = json.loads(_dpapi(base64.b64decode(store["protected_credentials"], validate=True), decrypt=True))
        if not isinstance(result, dict) or any(k not in SECRET_NAMES or not isinstance(v, str) for k, v in result.items()):
            raise ValueError()
        return result
    except Exception:
        raise ValueError("无法解密本机凭据；需使用保存时的 Windows 账号和电脑，不会自动回退到旧密钥") from None


def options_for(settings) -> dict:
    ds = settings.raw["deepseek"]
    return {"model": ds.get("model", "deepseek-v4-flash"), "thinking": bool(ds.get("thinking", False)),
            "daily_budget_usd": float(ds.get("daily_budget_usd", .30)),
            "input_usd_per_million": float(ds.get("input_usd_per_million", .22)),
            "output_usd_per_million": float(ds.get("output_usd_per_million", .66)),
            "telegram_enabled": bool(settings.raw.get("telegram", {}).get("enabled", True)),
            "zotero_enabled": bool(settings.raw.get("zotero", {}).get("enabled", True))}


def apply_options(raw: dict, options: dict) -> None:
    for name in ("model", "thinking", "daily_budget_usd", "input_usd_per_million", "output_usd_per_million"):
        if name in options:
            raw["deepseek"][name] = options[name]
    for section in ("telegram", "zotero"):
        if section + "_enabled" in options:
            raw.setdefault(section, {})["enabled"] = options[section + "_enabled"]


def public_connections(settings) -> dict:
    return {"options": options_for(settings), "credentials": {name: bool(settings.secret(name)) for name in SECRET_NAMES},
            "can_store_credentials": os.name == "nt", "storage": "Windows 当前用户加密" if os.name == "nt" else "本机 .env / 环境变量",
            "provider": "DeepSeek 官方接口", "base_url": settings.raw["deepseek"].get("base_url", "https://api.deepseek.com"),
            "vault": str(settings.vault), "local_only": True}


def save_connections(root: Path, payload: dict) -> None:
    from .config import load_settings
    if set(payload) - {"options", "credentials"}:
        raise ValueError("不支持的配置字段")
    with LOCK:
        settings = load_settings(root)
        options = options_for(settings)
        incoming = payload.get("options", {})
        if not isinstance(incoming, dict) or set(incoming) - set(options):
            raise ValueError("无效连接设置")
        options.update(incoming)
        if not isinstance(options["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", options["model"]):
            raise ValueError("模型名称不合法")
        for name in ("thinking", "telegram_enabled", "zotero_enabled"):
            if not isinstance(options[name], bool):
                raise ValueError("开关必须为布尔值")
        for name in ("daily_budget_usd", "input_usd_per_million", "output_usd_per_million"):
            value = options[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1000:
                raise ValueError("预算和估算单价须为 0 到 1000 的有效数值")
        credentials = payload.get("credentials", {})
        if not isinstance(credentials, dict) or set(credentials) - set(SECRET_NAMES):
            raise ValueError("不允许保存未知凭据")
        replacement = {}
        for name, value in credentials.items():
            if not isinstance(value, str) or len(value) > 1000 or any(c in value for c in "\r\n\0"):
                raise ValueError("凭据格式无效；不能包含换行")
            value = value.strip()
            if value:
                if name in {"TELEGRAM_CHAT_ID", "ZOTERO_USER_ID"} and not re.fullmatch(r"-?\d{1,24}", value):
                    raise ValueError("账号 ID 应填写数字，不是用户名")
                replacement[name] = value
        store = read_store(root)
        if replacement:
            values = protected_values(store)
            values.update(replacement)
            store["protected_credentials"] = base64.b64encode(_dpapi(json.dumps(values).encode())).decode("ascii")
        store["options"] = options
        path = root / "data" / "connections.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(prefix="connections-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(store, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
