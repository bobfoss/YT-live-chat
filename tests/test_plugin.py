from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yt_live_chat.database import database_status
from yt_live_chat.plugin import create_plugin

from tests.fixtures import CHAT_JSONL


class FakeContext:
    def __init__(self, root: Path, config_path: Path) -> None:
        self.root = root
        self.plugin_config = {"config": str(config_path)}

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path


class FakePlanningContext:
    def __init__(self, videos) -> None:
        self.videos = videos

    def library_videos(self):
        return list(self.videos)


class FakeRuntime:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.logs = []

    def stop_requested(self):
        return False

    def log(self, level, message, *, subject_id=""):
        self.logs.append((level, message, subject_id))

    def run_youtube_ytdlp(self, video_id, options, *, download):
        if self.available:
            output = Path(
                options["outtmpl"]
                .replace("%(id)s", video_id)
                .replace("%(ext)s", "live_chat.json")
            )
            output.write_text(CHAT_JSONL, encoding="utf-8")
            return {"id": video_id, "subtitles": {"live_chat": [{"ext": "json"}]}}
        return {"id": video_id, "subtitles": {}}


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
            self.assertEqual(plugin.required_host_features, {"youtube_ytdlp_v1"})
            self.assertEqual(
                plugin.capabilities,
                {
                    "video_live_chat_availability",
                    "video_live_chat_messages",
                    "channel_live_chat_history",
                    "worker_processes",
                },
            )
            self.assertEqual(
                plugin.browser_assets,
                (
                    {"path": "browser.css", "type": "style"},
                    {"path": "browser.js", "type": "script"},
                ),
            )
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
            process = plugin.worker_processes()[0]
            self.assertEqual(process["id"], "replay")
            self.assertEqual(process["service"], "youtube")
            self.assertEqual(process["hooks"], ("video_scan",))
            self.assertEqual(process["buttonLabel"], "Download recorded live chats")
            content_type, browser_script = plugin.handle_browser_asset("browser.js")
            self.assertEqual(content_type, "text/javascript; charset=utf-8")
            self.assertIn(b"id: 'live_chat'", browser_script)
            self.assertIn(b"entityCards: {", browser_script)
            self.assertIn(b"videoDetail: {", browser_script)
            self.assertIn(b"video_live_chat_messages", browser_script)
            self.assertIn(b"channelVideoTabs", browser_script)
            code, payload = plugin.handle_api(
                "GET",
                "channels/UCauthor1/videos",
                {"limit": ["1"], "offset": ["0"]},
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["total"], 0)
            content_type, browser_style = plugin.handle_browser_asset("browser.css")
            self.assertEqual(content_type, "text/css; charset=utf-8")
            self.assertIn(b".ytlc-panel", browser_style)
            with self.assertRaises(KeyError):
                plugin.handle_browser_asset("missing.js")

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
                    "worker_max_in_flight": 2,
                    "replay_retry_days": 7,
                },
            )

    def test_replay_worker_plans_only_ended_livestreams_and_ingests_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "yt_live_chat.config.json"
            plugin = create_plugin()
            plugin.start(FakeContext(root, config_path))
            context = FakePlanningContext(
                [
                    {
                        "video_id": "abcdefghijk",
                        "title": "Ended stream",
                        "video_type": "livestream",
                        "broadcast_status": "ended",
                        "broadcast_started_at": "2026-08-11T16:01:53Z",
                        "broadcast_ended_at": "2026-08-11T16:27:12Z",
                        "broadcast_status_checked_at": "2026-08-11T16:28:00Z",
                    },
                    {
                        "video_id": "lmnopqrstuv",
                        "title": "Active stream",
                        "video_type": "livestream",
                        "broadcast_status": "live",
                    },
                    {
                        "video_id": "zzzzzzzzzzz",
                        "title": "Unobserved stream",
                        "video_type": "livestream",
                        "broadcast_status": None,
                    },
                    {
                        "video_id": "yyyyyyyyyyy",
                        "title": "Ordinary video",
                        "video_type": "video",
                        "broadcast_status": "ended",
                    },
                ]
            )

            tasks = plugin.plan_worker("replay", context, {})

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["video_id"], "abcdefghijk")
            self.assertEqual(tasks[0]["payload"]["broadcast_ended_at"], "2026-08-11T16:27:12Z")
            targeted = plugin.plan_worker(
                "replay",
                context,
                {"hook": "video_scan", "video_id": ["abcdefghijk"]},
            )
            self.assertEqual(targeted, tasks)

            runtime = FakeRuntime()
            result = plugin.run_worker("replay", tasks[0], runtime)

            self.assertEqual(result["outcome"], "found")
            self.assertEqual(result["found"], 1)
            status = database_status(root / "yt_live_chat.sqlite3")
            self.assertEqual(status["capturedVideoCount"], 1)
            self.assertEqual(status["replayCaptureCount"], 1)
            self.assertEqual(status["actionCount"], 3)
            self.assertEqual(status["messageCount"], 2)
            self.assertEqual(plugin.plan_worker("replay", context, {}), [])
            code, payload = plugin.handle_api(
                "GET",
                "videos",
                {"id": ["abcdefghijk", "missing"]},
            )
            self.assertEqual(code, 200)
            self.assertEqual(
                payload["videos"]["abcdefghijk"]["replay_status"],
                "captured",
            )
            self.assertEqual(
                payload["videos"]["missing"]["replay_status"],
                "unobserved",
            )
            code, messages = plugin.handle_api(
                "GET",
                "videos/abcdefghijk/messages",
                {"limit": ["1"], "offset": ["1"]},
            )
            self.assertEqual(code, 200)
            self.assertEqual(messages["total"], 2)
            self.assertEqual(messages["messages"][0]["messageText"], ":heart:")
            code, invalid = plugin.handle_api(
                "GET",
                "videos/invalid/messages",
                {},
            )
            self.assertEqual(code, 400)
            self.assertIn("11-character", invalid["error"])
            code, invalid = plugin.handle_api(
                "GET",
                "videos/abcdefghijk/messages",
                {"limit": ["501"]},
            )
            self.assertEqual(code, 400)
            self.assertIn("between 1 and 500", invalid["error"])

    def test_replay_worker_records_observed_absence_without_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin = create_plugin()
            plugin.start(FakeContext(root, root / "yt_live_chat.config.json"))
            task = {
                "video_id": "abcdefghijk",
                "subject_id": "abcdefghijk",
                "payload": {},
            }

            result = plugin.run_worker(
                "replay",
                task,
                FakeRuntime(available=False),
            )

            self.assertEqual(result["outcome"], "not_available")
            code, payload = plugin.handle_api(
                "GET",
                "videos",
                {"id": ["abcdefghijk"]},
            )
            self.assertEqual(code, 200)
            self.assertEqual(
                payload["videos"]["abcdefghijk"]["replay_status"],
                "not_available",
            )


if __name__ == "__main__":
    unittest.main()
