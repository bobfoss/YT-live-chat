from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yt_live_chat.plugin import create_plugin


class FakeContext:
    def __init__(self, root: Path, config_path: Path) -> None:
        self.root = root
        self.plugin_config = {"config": str(config_path)}

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path


class PluginTests(unittest.TestCase):
    def test_plugin_bootstraps_storage_and_reports_admin_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "plugin" / "yt_live_chat.config.json"
            database_path = config_path.parent / "chat.sqlite3"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "database": "chat.sqlite3",
                        "capture_directory": "captures",
                    }
                ),
                encoding="utf-8",
            )
            plugin = create_plugin()

            plugin.start(FakeContext(root, config_path))
            status = plugin.status()

            self.assertEqual(plugin.plugin_id, "live_chat")
            self.assertEqual(plugin.plugin_name, "YT Live Chat")
            self.assertEqual(plugin.plugin_api_version, 2)
            self.assertEqual(plugin.capabilities, frozenset())
            self.assertEqual(plugin.browser_assets, ())
            self.assertTrue(database_path.is_file())
            self.assertEqual(status["state"], "ready")
            self.assertEqual(
                [metric["id"] for metric in status["adminMetrics"]],
                [
                    "captured-videos",
                    "live-captures",
                    "replay-captures",
                    "chat-actions",
                    "chat-messages",
                    "database-size",
                ],
            )
            self.assertTrue(
                all(
                    metric["value"] == 0
                    for metric in status["adminMetrics"][:-1]
                )
            )
            self.assertEqual(status["adminMetrics"][-1]["format"], "bytes")
            code, payload = plugin.handle_api("GET", "status", {})
            self.assertEqual(code, 200)
            self.assertEqual(payload["state"], "ready")
            self.assertIsNone(plugin.handle_api("POST", "status", {}))

            plugin.shutdown()
            self.assertEqual(plugin.status()["state"], "stopped")

    def test_plugin_creates_default_config_on_first_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "yt_live_chat.config.json"
            plugin = create_plugin()

            plugin.start(FakeContext(root, config_path))

            self.assertTrue(config_path.is_file())
            self.assertTrue((root / "yt_live_chat.sqlite3").is_file())
            self.assertEqual(
                json.loads(config_path.read_text(encoding="utf-8")),
                {
                    "database": "yt_live_chat.sqlite3",
                    "capture_directory": "captures",
                },
            )


if __name__ == "__main__":
    unittest.main()
