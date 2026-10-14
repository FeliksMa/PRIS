from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pris.config import load_settings
from pris.connections import _dpapi, options_for, public_connections, save_connections
from pris.telegram import TelegramClient
from pris.zotero import ZoteroClient

ROOT = Path(__file__).resolve().parent.parent


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copyfile(ROOT / "config.example.toml", self.root / "config.toml")

    def tearDown(self):
        self.temp.cleanup()

    def test_dotenv_is_workspace_local_and_not_in_settings_repr(self):
        (self.root / ".env").write_text("TELEGRAM_CHAT_ID=123456789\n", encoding="utf-8")
        with patch.dict(os.environ):
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            settings = load_settings(self.root)
            self.assertEqual(settings.secret("TELEGRAM_CHAT_ID"), "123456789")
            self.assertNotIn("TELEGRAM_CHAT_ID", os.environ)
            self.assertNotIn("123456789", repr(settings))

    def test_options_save_and_reload_without_changing_basic_config(self):
        before = (self.root / "config.toml").read_bytes()
        save_connections(self.root, {"options": {"model": "test-model", "daily_budget_usd": .05, "telegram_enabled": False, "zotero_enabled": False}})
        settings = load_settings(self.root)
        self.assertEqual(settings.raw["deepseek"]["model"], "test-model")
        self.assertEqual(settings.raw["deepseek"]["daily_budget_usd"], .05)
        self.assertEqual((self.root / "config.toml").read_bytes(), before)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123", "ZOTERO_API_KEY": "fake", "ZOTERO_USER_ID": "123"}):
            self.assertFalse(TelegramClient(settings).ready)
            self.assertFalse(ZoteroClient(settings).ready)

    def test_invalid_save_does_not_change_file_or_expose_value(self):
        save_connections(self.root, {"options": {"model": "test-model"}})
        path = self.root / "data" / "connections.json"
        before = path.read_bytes()
        for payload in [{"options": {"daily_budget_usd": float("nan")}}, {"options": {"base_url": "https://other.example"}}, {"credentials": {"DEEPSEEK_API_KEY": "private\nkey"}}, {"credentials": {"ZOTERO_USER_ID": "private-name"}}]:
            with self.assertRaises(ValueError) as err:
                save_connections(self.root, payload)
            self.assertNotIn("private", str(err.exception))
            self.assertEqual(path.read_bytes(), before)

    def test_encryption_failure_never_writes_plaintext_or_partial_options(self):
        with patch("pris.connections._dpapi", side_effect=ValueError("unavailable")):
            with self.assertRaises(ValueError):
                save_connections(self.root, {"options": {"model": "test-model"}, "credentials": {"DEEPSEEK_API_KEY": "fixture-only-key"}})
        self.assertFalse((self.root / "data" / "connections.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_windows_roundtrip_no_plaintext_no_echo_and_blank_retains(self):
        fixture = "fixture-only-private-api-key"
        save_connections(self.root, {"credentials": {"DEEPSEEK_API_KEY": fixture}})
        settings = load_settings(self.root)
        self.assertEqual(settings.secret("DEEPSEEK_API_KEY"), fixture)
        self.assertNotIn(fixture, (self.root / "data" / "connections.json").read_text())
        self.assertNotIn(fixture, json.dumps(public_connections(settings)))
        save_connections(self.root, {"credentials": {"DEEPSEEK_API_KEY": ""}, "options": {"model": "another-model"}})
        self.assertEqual(load_settings(self.root).secret("DEEPSEEK_API_KEY"), fixture)

    def test_corrupt_encrypted_store_fails_closed(self):
        path = self.root / "data" / "connections.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"options": {}, "protected_credentials": "not-valid-base64"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_settings(self.root)
