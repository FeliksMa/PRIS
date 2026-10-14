from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Assessment, Paper


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  authors_json TEXT NOT NULL,
  abstract TEXT NOT NULL,
  url TEXT NOT NULL,
  published TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL,
  field TEXT NOT NULL,
  doi TEXT NOT NULL,
  external_id TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  verification_note TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'discovered',
  discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS assessments (
  paper_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  assessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_update_id INTEGER UNIQUE,
  paper_id TEXT,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def upsert_paper(self, paper: Paper) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO papers
                (id,title,authors_json,abstract,url,published,source,source_type,field,doi,external_id,verified,verification_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title, authors_json=excluded.authors_json,
                  abstract=excluded.abstract, url=excluded.url, published=excluded.published,
                  doi=excluded.doi, external_id=excluded.external_id,
                  verified=excluded.verified, verification_note=excluded.verification_note,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    paper.id, paper.title, json.dumps(paper.authors, ensure_ascii=False),
                    paper.abstract, paper.url, paper.published, paper.source,
                    paper.source_type, paper.field, paper.doi, paper.external_id,
                    int(paper.verified), paper.verification_note,
                ),
            )

    def save_assessment(self, assessment: Assessment) -> None:
        payload = {name: getattr(assessment, name) for name in assessment.__dataclass_fields__}
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO assessments(paper_id,payload_json,assessed_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                (assessment.paper_id, json.dumps(payload, ensure_ascii=False)),
            )

    def get_assessment(self, paper_id: str) -> Assessment | None:
        with self.connect() as con:
            row = con.execute("SELECT payload_json FROM assessments WHERE paper_id=?", (paper_id,)).fetchone()
        return Assessment(**json.loads(row["payload_json"])) if row else None

    def set_status(self, paper_id: str, status: str) -> None:
        with self.connect() as con:
            con.execute("UPDATE papers SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, paper_id))

    def get_paper(self, paper_id: str) -> Paper | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not row:
            return None
        return Paper(
            title=row["title"], authors=json.loads(row["authors_json"]), abstract=row["abstract"],
            url=row["url"], published=row["published"], source=row["source"],
            source_type=row["source_type"], field=row["field"], doi=row["doi"],
            external_id=row["external_id"], verified=bool(row["verified"]),
            verification_note=row["verification_note"],
        )

    def pending_deep_reads(self) -> list[Paper]:
        with self.connect() as con:
            rows = con.execute("SELECT id FROM papers WHERE status='deep_requested'").fetchall()
        return [paper for row in rows if (paper := self.get_paper(row["id"]))]

    def pending_zotero(self) -> list[Paper]:
        with self.connect() as con:
            rows = con.execute("SELECT id FROM papers WHERE status='deep_prepared'").fetchall()
        return [paper for row in rows if (paper := self.get_paper(row["id"]))]

    def record_feedback(self, update_id: int, text: str, paper_id: str = "") -> bool:
        try:
            with self.connect() as con:
                con.execute(
                    "INSERT INTO feedback(telegram_update_id,paper_id,text) VALUES(?,?,?)",
                    (update_id, paper_id or None, text),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def state(self, key: str, default: str = "") -> str:
        with self.connect() as con:
            row = con.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES(?,?)", (key, value))

    def record_usage(self, date: str, model: str, input_tokens: int, output_tokens: int, cost: float) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO usage(run_date,model,input_tokens,output_tokens,cost_usd) VALUES(?,?,?,?,?)",
                (date, model, input_tokens, output_tokens, cost),
            )

    def daily_cost(self, date: str) -> float:
        with self.connect() as con:
            row = con.execute("SELECT COALESCE(SUM(cost_usd),0) AS total FROM usage WHERE run_date=?", (date,)).fetchone()
        return float(row["total"])
