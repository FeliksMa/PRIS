from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .config import Settings
from .db import Database
from .http import get_json, post_json


class TelegramClient:
    def __init__(self, settings: Settings):
        self.token = settings.secret("TELEGRAM_BOT_TOKEN")
        self.chat_id = settings.secret("TELEGRAM_CHAT_ID")
        self.base = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        if not self.ready:
            return
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": True}
            if reply_markup and index == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            post_json(f"{self.base}/sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str) -> None:
        post_json(f"{self.base}/answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def updates(self, offset: int, limit: int = 100) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        url = f"{self.base}/getUpdates?offset={offset}&limit={limit}&timeout=0"
        return get_json(url).get("result", [])

    def discover_private_chats(self) -> list[tuple[str, str]]:
        """Return chat IDs that have recently messaged the bot; token is never printed."""
        if not self.token:
            return []
        updates = get_json(f"{self.base}/getUpdates?limit=100&timeout=0").get("result", [])
        chats: dict[str, str] = {}
        for update in updates:
            message = update.get("message") or update.get("callback_query", {}).get("message", {})
            chat = message.get("chat", {})
            if chat.get("type") == "private" and chat.get("id") is not None:
                label = chat.get("username") or " ".join(
                    part for part in (chat.get("first_name", ""), chat.get("last_name", "")) if part
                )
                chats[str(chat["id"])] = label or "private chat"
        return list(chats.items())


DEEP_RE = re.compile(r"(?:深读|深入阅读|保留)(?:第)?\s*(\d+)\s*(?:篇)?", re.I)


def poll_feedback(settings: Settings, db: Database) -> int:
    client = TelegramClient(settings)
    if not client.ready:
        return 0
    offset = int(db.state("telegram_offset", "0"))
    latest_ids = json.loads(db.state("latest_focus_ids", "[]"))
    handled = 0
    for update in client.updates(offset, int(settings.raw.get("telegram", {}).get("poll_limit", 100))):
        update_id = int(update["update_id"])
        offset = max(offset, update_id + 1)
        callback = update.get("callback_query")
        message = update.get("message", {})
        source_message = callback.get("message", {}) if callback else message
        source_chat_id = str(source_message.get("chat", {}).get("id", ""))
        if source_chat_id != str(client.chat_id):
            continue
        text = (message.get("text") or "").strip()
        paper_id = ""
        action = "feedback"
        if callback:
            data = callback.get("data", "")
            action, _, paper_id = data.partition(":")
            text = f"callback:{data}"
        else:
            match = DEEP_RE.search(text)
            if match:
                index = int(match.group(1)) - 1
                if 0 <= index < len(latest_ids):
                    paper_id, action = latest_ids[index], "deep"
        if db.record_feedback(update_id, text, paper_id):
            handled += 1
            folder = settings.vault / "06 反馈记录"
            folder.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            feedback_path = folder / f"{now:%Y-%m} Telegram 反馈.md"
            with feedback_path.open("a", encoding="utf-8") as fh:
                fh.write(f"- {now:%Y-%m-%d %H:%M} | paper={paper_id or 'general'} | {text}\n")
            if paper_id and action == "deep":
                db.set_status(paper_id, "deep_requested")
                client.send("已加入深度阅读队列。系统会先保存真实书目信息和 DOI，等待你提供全文。")
            elif paper_id and action == "skip":
                db.set_status(paper_id, "not_interested")
            elif not callback and text == "/start":
                client.send(
                    "PRIS 已连接。\n\n"
                    "你可以回复：\n"
                    "• 深读第2篇——加入深读与 Zotero 队列\n"
                    "• 这篇太理论/这类内容多推一些——记录兴趣反馈\n"
                    "• 任何普通评价——保存到 Obsidian 反馈记录\n\n"
                    "目前消息由定时轮询处理，因此回复可能有几分钟延迟。"
                )
            elif not callback and text:
                client.send("反馈已记录，会用于后续推荐调整。")
            if callback:
                client.answer_callback(callback["id"], "反馈已记录")
    db.set_state("telegram_offset", str(offset))
    return handled
