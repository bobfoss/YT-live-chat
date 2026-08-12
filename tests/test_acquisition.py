from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yt_live_chat.acquisition import download_recorded_chat

from tests.fixtures import CHAT_JSONL


class FakeRuntime:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls = []

    def run_youtube_ytdlp(self, video_id, options, *, download):
        self.calls.append((video_id, options, download))
        if self.available:
            output = Path(
                options["outtmpl"]
                .replace("%(id)s", video_id)
                .replace("%(ext)s", "live_chat.json")
            )
            output.write_text(CHAT_JSONL, encoding="utf-8")
            return {"id": video_id, "subtitles": {"live_chat": [{"ext": "json"}]}}
        return {"id": video_id, "subtitles": {}}


class AcquisitionTests(unittest.TestCase):
    def test_download_uses_host_service_and_finalizes_content_addressed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_directory = Path(temp_dir) / "captures"
            runtime = FakeRuntime()

            result = download_recorded_chat(
                "abcdefghijk",
                capture_directory,
                runtime,
            )

            self.assertEqual(result.status, "captured")
            self.assertEqual(result.parsed.message_count, 2)
            self.assertEqual(len(result.source_sha256), 64)
            self.assertTrue(result.source_path.endswith(".jsonl"))
            artifact = capture_directory / result.source_path
            self.assertTrue(artifact.is_file())
            self.assertEqual(artifact.read_text(encoding="utf-8"), CHAT_JSONL)
            video_id, options, download = runtime.calls[0]
            self.assertEqual(video_id, "abcdefghijk")
            self.assertTrue(download)
            self.assertEqual(options["subtitleslangs"], ["live_chat"])
            self.assertNotIn("cookiefile", options)
            self.assertNotIn("proxy", options)

            duplicate = download_recorded_chat(
                "abcdefghijk",
                capture_directory,
                runtime,
            )
            self.assertEqual(duplicate.source_path, result.source_path)
            self.assertEqual(len(list(capture_directory.rglob("*.jsonl"))), 1)

    def test_download_records_observed_absence_without_creating_an_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = download_recorded_chat(
                "abcdefghijk",
                Path(temp_dir) / "captures",
                FakeRuntime(available=False),
            )

            self.assertEqual(result.status, "not_available")
            self.assertEqual(result.source_path, "")


if __name__ == "__main__":
    unittest.main()
