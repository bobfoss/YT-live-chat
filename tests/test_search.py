from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from yt_live_chat.database import initialize_database, record_replay_observation, store_replay_capture
from yt_live_chat.jsonl import parse_chat_jsonl
from yt_live_chat.plugin import create_plugin
from tests.fixtures import CHAT_JSONL


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = initialize_database(self.root / "chat.sqlite3")
        self.plugin = create_plugin()
        self.plugin._database_path = self.database
        self.lookups = []

        def videos(ids):
            self.lookups.append(list(ids))
            return [{"video_id": key, "title": f"Video {key}"} for key in ids]

        self.plugin._library_videos = videos
        self.capture("abcdefghijk", "good morning", "2026-01-01")
        self.capture("lmnopqrstuv", "morning sunshine", "2026-02-01")

    def capture(self, video_id, message, day, *, dates=True):
        text = CHAT_JSONL.replace("good morning", message)
        path = self.root / "chat.jsonl"
        path.write_text(text, encoding="utf-8")
        return store_replay_capture(
            self.database, video_id, source_path="chat.jsonl",
            source_sha256=hashlib.sha256(text.encode()).hexdigest(), source_bytes=len(text.encode()),
            yt_dlp_version="test", parsed=parse_chat_jsonl(path), started_at=f"{day}T03:00:00Z",
            broadcast_started_at=f"{day}T01:00:00Z" if dates else None,
            broadcast_ended_at=f"{day}T02:00:00Z" if dates else None,
            broadcast_status_checked_at=None,
        )

    def collection(self, **params):
        code, payload = self.plugin.handle_api("GET", "collection", {key: [str(value)] for key, value in params.items()})
        self.assertEqual(code, 200)
        return payload

    def test_blank_global_omits_cards_but_collection_browses_and_facets_keep_presence(self):
        self.assertEqual(self.plugin.search_result_descriptors("  "), [])
        self.assertEqual(self.lookups, [])
        self.assertEqual(self.plugin.filter_videos(""), {
            "video_ids": frozenset({"abcdefghijk", "lmnopqrstuv"}), "search_match_ids": frozenset(),
        })
        page = self.collection()
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["totalIsExact"])
        self.assertEqual([item["video_id"] for item in page["results"]], ["lmnopqrstuv", "abcdefghijk"])
        self.assertEqual(len(page["results"][0]["messages"]), 2)

    def test_prefix_matches_only_message_text_and_all_authors_are_eligible(self):
        self.assertEqual(self.plugin.filter_videos("morn")["search_match_ids"], {"abcdefghijk", "lmnopqrstuv"})
        self.assertEqual(self.plugin.filter_videos("good morn")["search_match_ids"], {"abcdefghijk"})
        self.assertEqual(self.plugin.filter_videos("heart")["search_match_ids"], {"abcdefghijk", "lmnopqrstuv"})
        for query in ("replay", "First author", "Video", "!!!", "123456", '" OR *'):
            with self.subTest(query=query):
                self.assertEqual(self.plugin.search_result_descriptors(query), [])
                self.assertEqual(self.collection(q=query)["total"], 0)

    def test_descriptors_group_current_chat_with_broadcast_dates_and_no_likes(self):
        rows = self.plugin.search_result_descriptors("morn")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {
            "id": "chat:abcdefghijk", "video_id": "abcdefghijk", "title": "Video abcdefghijk",
            "oldest_at": "2026-01-01T01:00:00Z", "newest_at": "2026-01-01T02:00:00Z", "like_count": None,
        })
        self.assertEqual(len({row["id"] for row in rows}), 2)
        self.capture("ZYXWVUTSRQP", "morning", "2026-03-01", dates=False)
        fallback = self.plugin.search_result_descriptors("morn")
        item = next(row for row in fallback if row["video_id"] == "ZYXWVUTSRQP")
        self.assertEqual(item["oldest_at"], item["newest_at"])
        self.assertTrue(item["newest_at"].endswith("Z"))

    def test_only_requested_cards_are_hydrated_with_matching_excerpt_and_offset(self):
        items = self.plugin.hydrate_search_results(["chat:abcdefghijk", "chat:missing", "invalid"], "good morn")
        self.assertEqual(list(items), ["chat:abcdefghijk"])
        message = items["chat:abcdefghijk"]["messages"][0]
        self.assertEqual(message["offsetMs"], 20485)
        self.assertIn("<mark>morning</mark>", message["snippet"])
        self.assertEqual(self.plugin.hydrate_search_results(["chat:abcdefghijk"], "unmatched"), {})
        self.assertEqual(self.plugin.hydrate_search_results([], "morning"), {})

    def test_superseded_captures_and_status_changes_invalidate_cached_matches(self):
        self.assertEqual(self.plugin.filter_videos("good")["search_match_ids"], {"abcdefghijk"})
        self.capture("abcdefghijk", "a replacement conversation", "2026-04-01")
        self.assertEqual(self.plugin.filter_videos("good")["search_match_ids"], set())
        self.assertEqual(self.plugin.search_result_descriptors("good"), [])
        self.assertEqual(self.plugin.hydrate_search_results(["chat:abcdefghijk"], "good"), {})
        self.assertEqual(self.collection(q="replacement")["total"], 1)
        record_replay_observation(self.database, "abcdefghijk", "unavailable")
        self.assertEqual(self.collection(q="replacement")["total"], 0)
        self.assertEqual(self.plugin.filter_videos("")["video_ids"], {"lmnopqrstuv"})
        self.assertEqual(self.plugin.status()["searchCatalogCount"], 1)

    def test_collection_orders_and_pages_before_hydration(self):
        first = self.collection(q="morn", sort="oldest", limit=1)
        second = self.collection(q="morn", sort="oldest", limit=1, offset=1)
        self.assertEqual(first["results"][0]["id"], "chat:abcdefghijk")
        self.assertEqual(second["results"][0]["id"], "chat:lmnopqrstuv")
        self.assertEqual(first["total"], second["total"])
        self.assertEqual(self.collection(q="morn", limit=1, offset=99)["offset"], 1)
        self.assertEqual(self.collection(q="missing", limit=1, offset=99)["offset"], 0)
        for params in ({"limit": ["0"]}, {"limit": ["501"]}, {"offset": ["-1"]}, {"sort": ["most_liked"]}):
            self.assertEqual(self.plugin.handle_api("GET", "collection", params)[0], 400)

    def test_author_options_filter_messages_not_capture_presence(self):
        identity = self.plugin._account_identity = Mock(return_value={"channel_id": "UCauthor1"})
        own = {"own": True, "others": False}
        others = {"own": False, "others": True}
        self.assertEqual(self.plugin.search_result_descriptors("heart", filters=own), [])
        self.assertEqual(len(self.plugin.search_result_descriptors("morn", filters=own)), 2)
        self.assertEqual(self.plugin.search_result_descriptors("morn", filters=others), [])
        self.assertEqual(len(self.plugin.search_result_descriptors("heart", filters=others)), 2)
        for filters in (own, others, {"own": False, "others": False}):
            self.assertEqual(self.plugin.filter_videos("morn", filters=filters)["video_ids"],
                             {"abcdefghijk", "lmnopqrstuv"})
        for options, author in (({"own": 1, "others": 0}, "UCauthor1"), ({"own": 0, "others": 1}, "UCauthor2")):
            page = self.collection(**options)
            self.assertEqual(page["total"], 2)
            self.assertEqual({message["authorChannelId"] for card in page["results"] for message in card["messages"]}, {author})
        self.assertEqual(self.collection(own=0, others=0)["total"], 0)
        self.assertEqual(self.plugin.hydrate_search_results(["chat:abcdefghijk"], "morn", filters=others), {})
        self.assertEqual(self.plugin.hydrate_search_results(["chat:abcdefghijk"], "morn", filters=own)["chat:abcdefghijk"]["messages"][0]["authorChannelId"], "UCauthor1")
        identity.reset_mock()
        self.plugin.search_result_descriptors("morn")
        self.plugin.search_result_descriptors("", filters=own)
        self.plugin.filter_videos("", filters=own)
        self.collection()
        self.collection(own=0, others=0)
        identity.assert_not_called()

    def test_author_cache_tracks_identity_and_current_capture_and_fails_closed(self):
        self.plugin._account_identity = Mock(return_value={"channel_id": "UCauthor1"})
        own = {"others": False}
        self.assertEqual(len(self.plugin.search_result_descriptors("morn", filters=own)), 2)
        self.plugin._account_identity.return_value = {"channel_id": "UCauthor2"}
        self.assertEqual(self.plugin.search_result_descriptors("morn", filters=own), [])
        self.assertEqual(len(self.plugin.search_result_descriptors("heart", filters=own)), 2)
        self.capture("abcdefghijk", "replacement", "2026-05-01")
        self.plugin._account_identity.return_value = {"channel_id": "UCauthor1"}
        self.assertEqual(len(self.plugin.search_result_descriptors("morn", filters=own)), 1)
        self.plugin._account_identity.side_effect = RuntimeError("Identity unavailable")
        self.assertEqual(self.plugin.handle_api("GET", "collection", {"others": ["0"]})[0], 503)
        self.assertEqual(self.collection()["total"], 2)
        with self.assertRaises(RuntimeError):
            self.plugin.search_result_descriptors("morn", filters=own)
        self.assertEqual(self.plugin.handle_api("GET", "collection", {"others": ["false"]})[0], 400)


if __name__ == "__main__":
    unittest.main()
