from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yt_live_chat.jsonl import parse_chat_jsonl

from tests.fixtures import CHAT_JSONL


class JsonlTests(unittest.TestCase):
    def test_parser_preserves_actions_and_classifies_user_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chat.jsonl"
            path.write_text(CHAT_JSONL, encoding="utf-8")

            parsed = parse_chat_jsonl(path)

            self.assertEqual(parsed.source_line_count, 3)
            self.assertEqual(len(parsed.actions), 3)
            self.assertEqual(parsed.message_count, 2)
            self.assertEqual(parsed.author_count, 2)
            self.assertEqual(parsed.first_offset_ms, 0)
            self.assertEqual(parsed.last_offset_ms, 1_482_532)
            self.assertEqual(parsed.actions[0].is_message, False)
            self.assertEqual(parsed.actions[1].message_text, "good morning")
            self.assertEqual(parsed.actions[2].message_text, ":heart:")
            self.assertEqual(
                parsed.actions[2].renderer_type,
                "liveChatTextMessageRenderer",
            )

    def test_parser_rejects_a_malformed_line_without_partial_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chat.jsonl"
            path.write_text(CHAT_JSONL + "{broken\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 4"):
                parse_chat_jsonl(path)


if __name__ == "__main__":
    unittest.main()
