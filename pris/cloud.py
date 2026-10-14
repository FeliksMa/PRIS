"""Cloud snapshot transport and GitHub Actions runner for private PRIS Sites."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_settings
from .db import Database
from .http import request
from .models import Assessment, Paper
from .preferences import public_preferences, save_overrides, validate_preferences
from .privacy import private_values, public_paper_url, research_export
from .connections import SECRET_NAMES

APPROVED_CLOUD_ORIGIN = "https://pris-research-desk.m35538181135.chatgpt.site"


def cloud_request(payload: dict | None = None) -> dict:
    base = os.environ.get("PRIS_CLOUD_URL", "").rstrip("/")
    access = os.environ.get("PRIS_SITE_ACCESS_TOKEN", "")
    runner = os.environ.get("PRIS_RUNNER_TOKEN", "")
    if base != APPROVED_CLOUD_ORIGIN or not access or not runner:
        raise ValueError("请配置 PRIS_CLOUD_URL、PRIS_SITE_ACCESS_TOKEN 和 PRIS_RUNNER_TOKEN")
    if payload is not None:
        payload = research_export(payload)
    raw = request(base + "/api/sync", method="POST" if payload is not None else "GET",
                  headers={"OAI-Sites-Authorization": f"Bearer {access}", "X-PRIS-Runner-Token": runner,
                           "Content-Type": "application/json"},
                  data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None, timeout=120)
    return json.loads(raw)


def snapshot(root: Path) -> dict:
    settings = load_settings(root)
    db = Database(settings.database)
    with db.connect() as con:
        rows = con.execute("SELECT p.*,a.payload_json FROM papers p LEFT JOIN assessments a ON a.paper_id=p.id").fetchall()
        papers = []
        for row in rows:
            p = dict(row)
            p["authors"] = json.loads(p.pop("authors_json"))
            p["assessment"] = json.loads(p.pop("payload_json") or "null")
            p["url"] = public_paper_url(p["url"])
            papers.append(p)
        usage = [dict(r) for r in con.execute("SELECT run_date,SUM(cost_usd) cost,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens FROM usage GROUP BY run_date")]
        feedback = [dict(r) for r in con.execute("SELECT f.*,p.title FROM feedback f LEFT JOIN papers p ON p.id=f.paper_id ORDER BY f.id DESC LIMIT 100")]
    base = settings.vault / "01 每日简报"
    reports = [{"path": str(p.relative_to(base)).replace("\\", "/"), "name": p.stem, "date": p.name[:10],
                "content": p.read_text(encoding="utf-8")} for p in base.rglob("*.md")] if base.exists() else []
    return research_export({
        "papers": papers, "reports": reports, "preferences": public_preferences(settings.raw), "usage": usage,
        "feedback": feedback, "runner": {"model": settings.raw["deepseek"].get("model"),
                                          "telegram": bool(settings.secret("TELEGRAM_BOT_TOKEN") and settings.secret("TELEGRAM_CHAT_ID")),
                                          "zotero": bool(settings.secret("ZOTERO_API_KEY") and settings.secret("ZOTERO_USER_ID")),
                                          "last_sync": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()},
    }, credentials=private_values() + [settings.secret(name) for name in SECRET_NAMES if len(settings.secret(name)) >= 5])


def upload(root: Path, initial: bool = False, last_nightly: str = "") -> None:
    value = snapshot(root)
    papers = value.pop("papers")
    for start in range(0, len(papers), 100):
        cloud_request({"papers": papers[start:start + 100], "initial": initial})
    value["initial"] = initial
    if last_nightly:
        value["last_nightly_date"] = last_nightly
    result = cloud_request(value)
    print(f"Cloud synchronized: {result.get('paper_count')} papers, {result.get('report_count')} reports")


def hydrate(root: Path, remote: dict) -> None:
    settings = load_settings(root)
    db = Database(settings.database)
    if remote.get("preferences"):
        allowed = {feed["name"] for feed in settings.raw.get("sources", {}).get("rss", [])}
        save_overrides(root, validate_preferences(remote["preferences"], allowed))
    for row in remote.get("papers", []):
        paper = Paper(title=row["title"], authors=row["authors"], abstract=row.get("abstract", ""), url=row["url"],
                      published=row.get("published", ""), source=row["source"], source_type=row["source_type"], field=row["field"],
                      doi=row.get("doi", ""), external_id=row.get("external_id", ""), verified=bool(row.get("verified")),
                      verification_note=row.get("verification_note", ""))
        if paper.id != row["id"]:
            raise ValueError("云端论文标识与元数据不符")
        db.upsert_paper(paper)
        db.set_status(paper.id, row.get("status", "discovered"))
        if row.get("assessment"):
            db.save_assessment(Assessment(**row["assessment"]))


def execute(root: Path) -> None:
    from .app import process_deep_reads, run_daily
    from .telegram import poll_feedback
    remote = cloud_request()
    hydrate(root, remote)
    settings = load_settings(root)
    db = Database(settings.database)
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    date = today.date().isoformat()
    last = remote.get("last_nightly_date", "")
    # The runner checks Beijing time and persists the completed date. Delayed
    # GitHub cron runs may catch up, without generating a second daily brief.
    nightly_due = (today.hour > 0 or today.minute >= 30) and last != date
    claimed = cloud_request({"action": "claim"}).get("job")
    try:
        command = claimed.get("command") if claimed else ""
        if command == "run" or nightly_due:
            run_daily(settings)
            last = date
        else:
            poll_feedback(settings, db)
            process_deep_reads(settings, db)
        upload(root, last_nightly=last)
        if claimed:
            cloud_request({"action": "complete", "id": claimed["id"], "success": True, "output": "云端操作完成，资料已同步。"})
    except Exception:
        if claimed:
            cloud_request({"action": "complete", "id": claimed["id"], "success": False, "output": "运行失败，已隐藏错误详情以保护凭据及研究内容。"})
        raise RuntimeError("云端研究任务失败，敏感错误详情未写入日志") from None


def main():
    parser = argparse.ArgumentParser(description="PRIS private cloud transport")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--initial-upload", action="store_true")
    args = parser.parse_args()
    if args.initial_upload:
        upload(args.root, initial=True)
    else:
        execute(args.root)


if __name__ == "__main__":
    main()
