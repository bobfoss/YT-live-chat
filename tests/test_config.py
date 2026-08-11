from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yt_live_chat.config import DEFAULT_CONFIG, config_path, ensure_config_file, load_config


class ConfigTests(unittest.TestCase):
    def test_default_config_contains_only_plugin_owned_storage(self) -> None:
        self.assertEqual(
            DEFAULT_CONFIG,
            {
                "database": "yt_live_chat.sqlite3",
                "capture_directory": "captures",
            },
        )
        self.assertNotIn("youtube_cookies", DEFAULT_CONFIG)
        self.assertNotIn("proxy", DEFAULT_CONFIG)

    def test_config_is_created_and_relative_paths_resolve_beside_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "settings" / "yt_live_chat.config.json"
            config = load_config(path)

            self.assertEqual(ensure_config_file(config), path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), DEFAULT_CONFIG)
            self.assertEqual(
                config_path(config, "database"),
                (path.parent / "yt_live_chat.sqlite3").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
