from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .collectors import collect_all
from .config import Settings, load_settings
from .db import Database
from .intelligence import assess, assign_tiers, heuristic_assessments, prefilter
from .manual import paper_from_pdf
from .outputs import add_featured_to_daily_report, telegram_brief, write_daily_report, write_deep_read_stub
from .telegram import TelegramClient, poll_feedback
from .validate import validate_paper
from .zotero import ZoteroClient


@contextmanager
def run_lock(root: Path) -> Iterator[None]:
    path = root / "data" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age > timedelta(hours=6):
            path.unlink(missing_ok=True)
        else:
            raise RuntimeError("另一个 PRIS 任务正在运行；本次已安全退出")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, f"pid={os.getpid()}\nstarted={datetime.now().isoformat()}".encode())
        os.close(fd)
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        path.unlink(missing_ok=True)


def process_deep_reads(settings: Settings, db: Database) -> tuple[int, int]:
    prepared = 0
    synced = 0
    for paper in db.pending_deep_reads():
        write_deep_read_stub(settings.vault, paper)
        db.set_status(paper.id, "deep_prepared")
        prepared += 1
    zotero = ZoteroClient(settings)
    if zotero.ready:
        for paper in db.pending_zotero():
            if zotero.add(paper):
                db.set_status(paper.id, "zotero_synced")
                synced += 1
    return prepared, synced


def run_daily(settings: Settings) -> Path:
    if not settings.is_active_runner:
        raise RuntimeError(
            f"本机 runner_id={settings.runner_id}，当前活动节点是 "
            f"{settings.raw['system'].get('active_runner_id')}；为避免重复推送，本次不运行"
        )
    db = Database(settings.database)
    with run_lock(settings.root):
        poll_feedback(settings, db)
        process_deep_reads(settings, db)
        discovered, errors = collect_all(settings.raw)
        candidates = prefilter(discovered, settings.raw)
        verified = []
        for paper in candidates:
            paper = validate_paper(paper)
            db.upsert_paper(paper)
            if paper.verified:
                verified.append(paper)
            else:
                errors.append(f"未进入推荐：{paper.title}｜{paper.verification_note}")
        if not verified:
            raise RuntimeError("本次没有通过真实性核验的候选内容，请检查来源连接")
        paper_map = {paper.id: paper for paper in verified}
        settings.raw["_paper_fields"] = {paper.id: paper.field for paper in verified}
        settings.raw["_paper_regions"] = {paper.id: paper.raw.get("region", "global") for paper in verified}
        settings.raw["_paper_source_types"] = {paper.id: paper.source_type for paper in verified}
        settings.raw["_paper_texts"] = {paper.id: f"{paper.title} {paper.abstract}".lower() for paper in verified}
        # First select the day's small, balanced reading set locally. Detailed LLM
        # analysis is only useful for the five focus items; asking it to expand all
        # collected candidates is costly and can truncate otherwise valid JSON.
        shortlist = assign_tiers(heuristic_assessments(verified, settings.raw), settings.raw)
        focus_ids = [item.paper_id for item in shortlist if item.tier == "focus"]
        focus_papers = [paper_map[paper_id] for paper_id in focus_ids if paper_id in paper_map]
        quick = [item for item in shortlist if item.tier == "quick"]
        detailed = []
        batch_size = int(settings.raw.get("deepseek", {}).get("batch_size", 5))
        for start in range(0, len(focus_papers), batch_size):
            batch = focus_papers[start:start + batch_size]
            try:
                detailed.extend(assess(batch, settings, db))
            except Exception as exc:
                errors.append(
                    f"DeepSeek 第 {start // batch_size + 1} 批分析失败，"
                    f"该批已使用本地保守摘要：{exc}"
                )
        detailed_map = {item.paper_id: item for item in detailed}
        focus = []
        for fallback in (item for item in shortlist if item.tier == "focus"):
            item = detailed_map.get(fallback.paper_id, fallback)
            item.tier = "focus"
            focus.append(item)
        assessments = focus + quick
        assessments = [item for item in assessments if item.paper_id in paper_map]
        for item in assessments:
            db.save_assessment(item)
        report = write_daily_report(settings.vault, paper_map, assessments, errors, settings.runner_id)
        focus_ids_ordered = [item.paper_id for item in assessments if item.tier == "focus"]
        db.set_state("latest_focus_ids", json.dumps(focus_ids_ordered))
        telegram = TelegramClient(settings)
        keyboard = {"inline_keyboard": [
            [
                {"text": f"深读 {index}", "callback_data": f"deep:{paper_id}"},
                {"text": f"略过 {index}", "callback_data": f"skip:{paper_id}"},
            ]
            for index, paper_id in enumerate(focus_ids_ordered, 1)
        ]}
        telegram.send(telegram_brief(paper_map, assessments), keyboard)
        return report


def doctor(settings: Settings) -> int:
    checks = {
        "活动运行节点": settings.is_active_runner,
        "DeepSeek API Key": bool(settings.secret("DEEPSEEK_API_KEY")),
        "Telegram Bot Token": bool(settings.secret("TELEGRAM_BOT_TOKEN")),
        "Telegram Chat ID": bool(settings.secret("TELEGRAM_CHAT_ID")),
        "Zotero API Key（深读同步需要）": bool(settings.secret("ZOTERO_API_KEY")),
        "Zotero User ID（深读同步需要）": bool(settings.secret("ZOTERO_USER_ID")),
    }
    print(f"PRIS 根目录：{settings.root}")
    print(f"Obsidian 输出：{settings.vault}")
    for name, ok in checks.items():
        print(f"[{'OK' if ok else '--'}] {name}")
    required = checks["DeepSeek API Key"] and checks["Telegram Bot Token"] and checks["Telegram Chat ID"]
    return 0 if required else 2


def send_latest(settings: Settings, db: Database) -> int:
    focus_ids = json.loads(db.state("latest_focus_ids", "[]"))
    papers = {paper_id: paper for paper_id in focus_ids if (paper := db.get_paper(paper_id))}
    assessments = [item for paper_id in focus_ids if (item := db.get_assessment(paper_id))]
    if not papers or not assessments:
        raise RuntimeError("没有可发送的最近日报，请先执行 run")
    for item in assessments:
        item.tier = "focus"
    keyboard = {"inline_keyboard": [
        [
            {"text": f"深读 {index}", "callback_data": f"deep:{paper_id}"},
            {"text": f"略过 {index}", "callback_data": f"skip:{paper_id}"},
        ]
        for index, paper_id in enumerate(focus_ids, 1)
    ]}
    TelegramClient(settings).send(telegram_brief(papers, assessments), keyboard)
    return len(assessments)


def ingest_featured_pdf(settings: Settings, db: Database, path: Path) -> Path:
    paper = paper_from_pdf(path)
    db.upsert_paper(paper)
    results = assess([paper], settings, db)
    item = results[0] if results else heuristic_assessments([paper], settings.raw)[0]
    item.tier = "focus"
    db.save_assessment(item)
    db.set_status(paper.id, "featured")
    report = add_featured_to_daily_report(settings.vault, paper, item)
    TelegramClient(settings).send(
        "\n".join([
            "PRIS 人工精选补充",
            "",
            paper.title,
            item.one_sentence,
            f"研究问题：{item.research_question}",
            f"核心原理与发现：{item.main_findings}",
            f"为什么值得看：{item.why_important}",
            f"证据状态：{item.evidence}",
            paper.verification_note,
        ]),
        {"inline_keyboard": [[{"text": "深读这篇", "callback_data": f"deep:{paper.id}"}]]},
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Research Intelligence System")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="PRIS 项目目录")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="执行每日研究流程")
    sub.add_parser("poll-feedback", help="读取一次 Telegram 反馈")
    sub.add_parser("process-deep", help="处理深读与 Zotero 队列")
    sub.add_parser("discover-telegram-chat", help="查找最近给 Bot 发过消息的私人 Chat ID")
    sub.add_parser("send-latest", help="将最近一次重点简报发送到 Telegram")
    sub.add_parser("test-telegram", help="发送 Telegram 连接确认与使用说明")
    ingest_pdf = sub.add_parser("ingest-pdf", help="核验本地 PDF 并作为人工精选加入今日日报")
    ingest_pdf.add_argument("path", type=Path)
    sub.add_parser("doctor", help="检查配置是否完整")
    ui = sub.add_parser("ui", help="打开本地 PRIS Research Desk")
    ui.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.root)
    db = Database(settings.database)
    try:
        if args.command == "run":
            print(run_daily(settings))
        elif args.command == "poll-feedback":
            print(f"已记录 {poll_feedback(settings, db)} 条新反馈")
        elif args.command == "process-deep":
            prepared, synced = process_deep_reads(settings, db)
            print(f"生成深读入口 {prepared} 条；同步 Zotero {synced} 条")
        elif args.command == "discover-telegram-chat":
            chats = TelegramClient(settings).discover_private_chats()
            if not chats:
                print("没有发现私人聊天。请先在 Telegram 中打开该 Bot 并发送一条消息。")
                return 2
            for chat_id, label in chats:
                print(f"{chat_id}\t{label}")
        elif args.command == "send-latest":
            print(f"已发送 {send_latest(settings, db)} 条重点内容")
        elif args.command == "test-telegram":
            TelegramClient(settings).send(
                "PRIS 已连接成功。你的 /start 和 hi 已经收到并保存。\n\n"
                "回复“深读第2篇”可加入深读队列；普通评价也会记录并用于调整推荐。"
            )
            print("Telegram 连接确认已发送")
        elif args.command == "ingest-pdf":
            print(ingest_featured_pdf(settings, db, args.path))
        elif args.command == "doctor":
            return doctor(settings)
        elif args.command == "ui":
            from .dashboard import serve
            serve(settings.root, args.port)
    except Exception as exc:
        try:
            TelegramClient(settings).send(f"PRIS 运行失败：{exc}")
        except Exception:
            pass
        print(f"PRIS 运行失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
