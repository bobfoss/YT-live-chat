from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yt_live_chat.database import (
    INTEGRATION_CONTRACT_VERSION,
    SCHEMA_VERSION,
    connect,
    database_status,
    initialize_database,
)


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


if __name__ == "__main__":
    unittest.main()
