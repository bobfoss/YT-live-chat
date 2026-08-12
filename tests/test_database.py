from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from yt_live_chat.database import (
    INTEGRATION_CONTRACT_VERSION,
    SCHEMA_VERSION,
    connect,
    database_status,
    initialize_database,
    list_video_messages,
    record_replay_observation,
    replay_states,
    store_replay_capture,
    video_replay_status,
)
from yt_live_chat.jsonl import parse_chat_jsonl

from tests.fixtures import CHAT_JSONL


class DatabaseTests(unittest.TestCase):
    def test_initialize_database_creates_compatible_zero_state_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "live-chat.sqlite3"

            self.assertEqual(initialize_database(database), database.resolve())
            status = database_status(database)

            self.assertTrue(status["available"])
            self.assertTrue(status["compatible"])
            self.assertEqual(status["schemaVersion"], SCHEMA_VERSION)
            self.assertEqual(
                status["integrationContractVersion"],
                INTEGRATION_CONTRACT_VERSION,
            )
            self.assertEqual(status["capturedVideoCount"], 0)
            self.assertEqual(status["liveCaptureCount"], 0)
            self.assertEqual(status["replayCaptureCount"], 0)
            self.assertEqual(status["actionCount"], 0)
            self.assertEqual(status["messageCount"], 0)
            self.assertGreater(status["databaseBytes"], 0)

    def test_database_status_reads_cached_catalog_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = initialize_database(Path(temp_dir) / "live-chat.sqlite3")
            conn = connect(database)
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE catalog_stats
                        SET captured_video_count = 2,
                            live_capture_count = 1,
                            replay_capture_count = 2,
                            action_count = 64,
                            message_count = 63,
                            source_byte_count = 112151
                        WHERE singleton = 1
                        """
                    )
            finally:
                conn.close()

            status = database_status(database)

            self.assertEqual(status["capturedVideoCount"], 2)
            self.assertEqual(status["liveCaptureCount"], 1)
            self.assertEqual(status["replayCaptureCount"], 2)
            self.assertEqual(status["actionCount"], 64)
            self.assertEqual(status["messageCount"], 63)
            self.assertEqual(status["sourceBytes"], 112151)

    def test_schema_one_database_upgrades_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "live-chat.sqlite3"
            conn = sqlite3.connect(database)
            try:
                with conn:
                    conn.executescript(
                        """
                        CREATE TABLE sidecar_metadata (
                          key TEXT PRIMARY KEY,
                          value TEXT NOT NULL
                        );
                        INSERT INTO sidecar_metadata(key, value)
                        VALUES ('schema_version', '1');
                        CREATE TABLE catalog_stats (
                          singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                          captured_video_count INTEGER NOT NULL DEFAULT 0,
                          live_capture_count INTEGER NOT NULL DEFAULT 0,
                          replay_capture_count INTEGER NOT NULL DEFAULT 0,
                          action_count INTEGER NOT NULL DEFAULT 0,
                          message_count INTEGER NOT NULL DEFAULT 0,
                          source_byte_count INTEGER NOT NULL DEFAULT 0,
                          updated_at TEXT NOT NULL
                        );
                        INSERT INTO catalog_stats(singleton, updated_at)
                        VALUES (1, '2026-08-11T00:00:00Z');
                        """
                    )
            finally:
                conn.close()

            initialize_database(database)
            status = database_status(database)

            self.assertTrue(status["compatible"])
            self.assertEqual(status["schemaVersion"], SCHEMA_VERSION)
            conn = connect(database, read_only=True)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                conn.close()
            self.assertTrue({"chat_targets", "chat_captures", "chat_actions"} <= tables)

    def test_capture_storage_is_idempotent_and_refreshes_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = initialize_database(root / "live-chat.sqlite3")
            jsonl = root / "chat.jsonl"
            jsonl.write_text(CHAT_JSONL, encoding="utf-8")
            parsed = parse_chat_jsonl(jsonl)
            arguments = {
                "source_path": "ab/abcdefghijk/replay-example.jsonl",
                "source_sha256": "a" * 64,
                "source_bytes": len(CHAT_JSONL.encode("utf-8")),
                "yt_dlp_version": "2026.07.04",
                "parsed": parsed,
                "started_at": "2026-08-11T16:30:00Z",
                "broadcast_started_at": "2026-08-11T16:01:53Z",
                "broadcast_ended_at": "2026-08-11T16:27:12Z",
                "broadcast_status_checked_at": "2026-08-11T16:28:00Z",
            }

            first = store_replay_capture(
                database,
                "abcdefghijk",
                **arguments,
            )
            duplicate = store_replay_capture(
                database,
                "abcdefghijk",
                **arguments,
            )

            self.assertTrue(first["created"])
            self.assertFalse(duplicate["created"])
            self.assertEqual(first["captureId"], duplicate["captureId"])
            status = database_status(database)
            self.assertEqual(status["capturedVideoCount"], 1)
            self.assertEqual(status["replayCaptureCount"], 1)
            self.assertEqual(status["actionCount"], 3)
            self.assertEqual(status["messageCount"], 2)
            replay = video_replay_status(database, ["abcdefghijk", "missing"])
            self.assertEqual(replay["abcdefghijk"]["replay_status"], "captured")
            self.assertEqual(replay["abcdefghijk"]["message_count"], 2)
            self.assertEqual(replay["missing"]["replay_status"], "unobserved")

            first_page = list_video_messages(
                database,
                "abcdefghijk",
                limit=1,
            )
            second_page = list_video_messages(
                database,
                "abcdefghijk",
                limit=1,
                offset=1,
            )
            self.assertEqual(first_page["captureId"], first["captureId"])
            self.assertEqual(first_page["total"], 2)
            self.assertEqual(len(first_page["messages"]), 1)
            self.assertEqual(first_page["messages"][0]["authorName"], "First author")
            self.assertEqual(first_page["messages"][0]["offsetMs"], 20485)
            self.assertEqual(second_page["messages"][0]["messageText"], ":heart:")
            missing_messages = list_video_messages(database, "missing")
            self.assertIsNone(missing_messages["captureId"])
            self.assertEqual(missing_messages["messages"], [])
            with self.assertRaisesRegex(ValueError, "between 1 and 500"):
                list_video_messages(database, "abcdefghijk", limit=501)
            with self.assertRaisesRegex(ValueError, "nonnegative"):
                list_video_messages(database, "abcdefghijk", offset=-1)

    def test_non_capture_replay_observations_remain_plugin_owned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = initialize_database(Path(temp_dir) / "live-chat.sqlite3")

            record_replay_observation(
                database,
                "abcdefghijk",
                "not_available",
                message="No recorded chat track",
            )

            state = replay_states(database)["abcdefghijk"]
            self.assertEqual(state["replay_status"], "not_available")
            self.assertEqual(state["last_error"], "No recorded chat track")


if __name__ == "__main__":
    unittest.main()
