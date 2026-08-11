"""Runtime configuration owned by YT Live Chat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "yt_live_chat.config.json"
DEFAULT_CONFIG: dict[str, Any] = {
    "database": "yt_live_chat.sqlite3",
    "capture_directory": "captures",
}


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file must contain a JSON object: {path}")
        config.update(
            {
                key: value
                for key, value in loaded.items()
                if key in DEFAULT_CONFIG and value is not None
            }
        )
    config["_config_path"] = str(path)
    return config


def ensure_config_file(config: dict[str, Any]) -> Path:
    path = Path(str(config.get("_config_path") or DEFAULT_CONFIG_PATH))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: config.get(key, value) for key, value in DEFAULT_CONFIG.items()}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def config_path(config: dict[str, Any], key: str) -> Path:
    value = Path(str(config[key]))
    if value.is_absolute():
        return value
    config_file = Path(str(config.get("_config_path") or DEFAULT_CONFIG_PATH)).resolve()
    return config_file.parent / value
