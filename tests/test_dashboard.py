from __future__ import annotations

import copy
import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from pris.config import load_settings
from pris.dashboard import Workspace
from pris.models import Paper
from pris.preferences import public_preferences, validate_preferences

ROOT = Path(__file__).resolve().parent.parent


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.example.toml", self.root / "config.toml")
        self.workspace = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_preferences_are_consumed_by_pipeline_and_audited(self):
        prefs = self.workspace.preferences()
        prefs["weights"] = {"economics": 70, "ai": 30, "humanities": 0}
        prefs["interests"]["economics"].append("ambiguity aversion")
        prefs["daily_focus"] = 10
        self.workspace.save(prefs, "测试配置")
        settings = load_settings(self.root)
        self.assertIn("ambiguity aversion", settings.raw["profile"]["interests"]["economics"])
        self.assertEqual(settings.raw["profile"]["daily_mix"]["focus"], {"economics": 7, "ai": 3, "humanities": 0})
        self.assertEqual(len(self.workspace.overview()["history"]), 1)

    def test_invalid_preferences_do_not_modify_saved_state(self):
        prefs = self.workspace.preferences()
        before = copy.deepcopy(prefs)
        prefs["weights"]["ai"] = float("nan")
        with self.assertRaises(ValueError):
            self.workspace.save(prefs, "invalid")
        self.assertEqual(self.workspace.preferences(), before)
        self.assertFalse((self.root / "data" / "preferences.json").exists())

    def test_report_path_cannot_escape_archive(self):
        with self.assertRaises(ValueError):
            self.workspace.report("../../../../.env")

    def test_chat_proposal_is_not_applied_until_user_action(self):
        prefs = self.workspace.preferences()
        changed = copy.deepcopy(prefs)
        changed["daily_focus"] = 12
        response = {"choices": [{"message": {"content": json.dumps({"reply": "请查看修改方案", "proposed_preferences": changed})}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), patch("pris.dashboard.post_json", return_value=response):
            result = self.workspace.chat("改成12篇")
        self.assertEqual(result["proposal"]["daily_focus"], 12)
        self.assertEqual(self.workspace.preferences()["daily_focus"], prefs["daily_focus"])
        self.assertEqual(len(self.workspace.messages()), 2)

    def test_http_session_csrf_search_and_preferences(self):
        paper = Paper("A new attention mechanism", ["Author"], "Test abstract", "https://example.org/paper", "2026-10-14", "Test", "preprint", "ai")
        self.workspace.db.upsert_paper(paper)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen([sys.executable, "-m", "pris.app", "--root", str(self.root), "ui", "--port", str(port)],
                                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            for _ in range(80):
                try:
                    with client.open(url, timeout=1) as response:
                        self.assertIn(b"Research Desk", response.read())
                    break
                except OSError:
                    time.sleep(.1)
            else:
                self.fail("dashboard did not start")
            with client.open(url + "/api/bootstrap") as response:
                data = json.load(response)
            self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(data))
            with client.open(url + "/api/papers?q=attention") as response:
                self.assertEqual(json.load(response)["total"], 1)
            payload = data["preferences"]
            payload["daily_focus"] = 12
            request = urllib.request.Request(url + "/api/preferences", data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json", "Origin": url}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as denied:
                client.open(request)
            self.assertEqual(denied.exception.code, 403)
            request.add_header("X-PRIS-Token", data["token"])
            with client.open(request) as response:
                self.assertEqual(json.load(response)["daily_focus"], 12)
            self.assertEqual(load_settings(self.root).raw["system"]["daily_focus"], 12)
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
