from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pris.db import Database
from pris.intelligence import assign_tiers, keyword_score, prefilter, remove_unsupported_speculation
from pris.collectors import is_recent
from pris.http import _safe_url
from pris.models import Assessment
from pris.models import Paper
from pris.outputs import safe_name, write_daily_report, write_deep_read_stub
from pris.validate import normalize_doi, normalize_title


def sample_paper() -> Paper:
    return Paper(
        title="Uncertainty and Household Consumption",
        authors=["Ada Economist"],
        abstract="We study uncertainty and decision making in household consumption.",
        url="https://doi.org/10.1234/example",
        published="2026-08-14",
        source="American Economic Review",
        source_type="peer_reviewed",
        field="economics",
        doi="10.1234/example",
        verified=True,
        verification_note="test",
    )


class CoreTests(unittest.TestCase):
    def test_unsupported_model_speculation_is_removed(self):
        item = Assessment(
            paper_id="p1", score=80, one_sentence="测试", why_important="测试",
            method="可能使用家庭内设计",
            main_findings="预期发现显著影响", technical_core="可能采用工具变量",
        )
        cleaned = remove_unsupported_speculation(item)
        self.assertIn("不能据此推断", cleaned.method)
        self.assertIn("不能据此推断", cleaned.main_findings)
        self.assertIn("不能据此推断", cleaned.technical_core)

    def test_http_errors_redact_telegram_token(self):
        safe = _safe_url("https://api.telegram.org/bot123:secret/getUpdates?token=also-secret&limit=1")
        self.assertNotIn("secret", safe)
        self.assertIn("bot<redacted>", safe)

    def test_normalize_doi(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1000/ABC."), "10.1000/abc")

    def test_normalize_title(self):
        self.assertEqual(normalize_title("Decision-Making: A Test"), "decision making a test")

    def test_database_round_trip_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "pris.db")
            paper = sample_paper()
            db.upsert_paper(paper)
            loaded = db.get_paper(paper.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, paper.title)
            db.set_status(paper.id, "deep_requested")
            self.assertEqual(db.pending_deep_reads()[0].id, paper.id)

    def test_keyword_score_rewards_interest_and_quality(self):
        config = {
            "profile": {
                "weights": {"economics": 0.6},
                "interests": {"economics": ["uncertainty", "consumption"]},
                "exclude": {"keywords": []},
            }
        }
        self.assertGreater(keyword_score(sample_paper(), config), 10)

    def test_ai_hard_exclusions_remove_circuit_design(self):
        paper = sample_paper()
        paper.field = "ai"
        paper.title = "An Agent for Analog Circuit Design"
        config = {
            "system": {"max_candidates": 50},
            "profile": {
                "weights": {"ai": 0.3},
                "interests": {"ai": ["agent"]},
                "exclude": {"keywords": []},
                "hard_exclude": {"ai": ["analog circuit", "circuit design"]},
            },
        }
        self.assertEqual(prefilter([paper], config), [])

    def test_deep_stub_states_no_full_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_deep_read_stub(Path(tmp), sample_paper())
            body = path.read_text(encoding="utf-8")
            self.assertIn("尚未取得并读取全文", body)
            self.assertIn("10.1234/example", body)

    def test_daily_report_contains_full_article_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = sample_paper()
            assessment = Assessment(
                paper_id=paper.id,
                score=90,
                one_sentence="文章研究不确定性如何改变家庭消费。",
                why_important="对应用户的核心研究方向。",
                research_question="收入不确定性是否压低当期消费？",
                background="传统模型与行为机制可能给出不同解释。",
                article_structure="先提出问题，再使用家庭数据识别效应，最后讨论机制。",
                method="使用家庭面板数据和外生冲击。",
                technical_core=r"核心关系为 $c_{it}=\beta u_{it}+X_{it}\gamma+\epsilon_{it}$。",
                main_findings="不确定性上升与消费下降相关。",
                contribution="连接了不确定性测量与家庭决策。",
                evidence="测试数据",
                limitations="需要检查识别假设。",
                connection="行为经济学与宏观消费。",
                reading_advice="值得深读。",
                tier="focus",
            )
            path = write_daily_report(Path(tmp), {paper.id: paper}, [assessment], [], "test")
            body = path.read_text(encoding="utf-8")
            self.assertIn("文章如何展开", body)
            self.assertIn("必要的数学或技术核心", body)
            self.assertIn("核心贡献", body)

    def test_safe_name(self):
        self.assertEqual(safe_name('A: Paper?'), "A- Paper-")

    def test_old_feed_items_are_rejected(self):
        self.assertFalse(is_recent("2024-11-15 10:00:05", 7))

    def test_daily_mix_keeps_economics_primary(self):
        items = [Assessment(str(i), 100 - i, "", "") for i in range(10)]
        config = {
            "system": {"daily_focus": 5, "daily_quick": 3},
            "profile": {"daily_mix": {
                "focus": {"economics": 3, "ai": 2},
                "quick": {"economics": 2, "ai": 1},
            }},
            "_paper_fields": {str(i): "ai" if i < 5 else "economics" for i in range(10)},
        }
        selected = assign_tiers(items, config)
        focus = [item for item in selected if item.tier == "focus"]
        econ = [item for item in focus if config["_paper_fields"][item.paper_id] == "economics"]
        self.assertEqual(len(econ), 3)

    def test_real_world_economics_deduplicates_same_indicator(self):
        items = [Assessment(name, score, "", "") for name, score in [
            ("cpi_release", 100), ("cpi_analysis", 99), ("labor", 98), ("trade", 97)
        ]]
        config = {
            "system": {"daily_focus": 3, "daily_quick": 0},
            "profile": {
                "economics_academic_share": 0,
                "daily_mix": {"focus": {"economics": 3}, "quick": {}},
            },
            "_paper_fields": {item.paper_id: "economics" for item in items},
            "_paper_regions": {item.paper_id: "global" for item in items},
            "_paper_source_types": {item.paper_id: "institution_analysis" for item in items},
            "_paper_texts": {
                "cpi_release": "consumer price index release",
                "cpi_analysis": "cpi interpretation",
                "labor": "employment and labor market",
                "trade": "exports and trade",
            },
        }
        selected = assign_tiers(items, config)
        ids = {item.paper_id for item in selected if item.tier == "focus"}
        self.assertEqual(len(ids & {"cpi_release", "cpi_analysis"}), 1)


if __name__ == "__main__":
    unittest.main()
