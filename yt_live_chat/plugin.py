"""YT Library plugin entry point for YT Live Chat."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .config import config_path, ensure_config_file, load_config
from .database import (
    INTEGRATION_CONTRACT_VERSION,
    SCHEMA_VERSION,
    database_status,
    initialize_database,
)


class YTLiveChatPlugin:
    plugin_id = "live_chat"
    plugin_name = "YT Live Chat"
    plugin_version = __version__
    plugin_api_version = 2
    capabilities: frozenset[str] = frozenset()
    browser_assets: tuple[dict[str, str], ...] = ()

    def __init__(self) -> None:
        self._database_path: Path | None = None
        self._config: dict[str, Any] = {}

    def start(self, context: Any) -> None:
        configured_path = str(context.plugin_config.get("config") or "").strip()
        own_config_path = context.resolve_path(configured_path) if configured_path else None
        own_config = load_config(own_config_path)
        ensure_config_file(own_config)
        database_path = config_path(own_config, "database")
        initialize_database(database_path)
        self._config = own_config
        self._database_path = database_path

    def status(self) -> dict[str, Any]:
        if self._database_path is None:
            return {
                "state": "stopped",
                "message": "Plugin has not been started",
            }
        status = database_status(self._database_path)
        state = "ready" if status.get("available") and status.get("compatible") else "unavailable"
        if status.get("available") and (
            status.get("schemaVersion") != SCHEMA_VERSION
            or status.get("integrationContractVersion")
            != INTEGRATION_CONTRACT_VERSION
        ):
            state = "incompatible"
        plugin_status: dict[str, Any] = {
            "state": state,
            "capabilities": sorted(self.capabilities),
            "database": status,
        }
        if state == "ready":
            plugin_status["adminMetrics"] = [
                {
                    "id": "captured-videos",
                    "label": "Captured videos",
                    "value": int(status["capturedVideoCount"]),
                    "format": "integer",
                    "description": "Videos with at least one stored live-chat capture.",
                },
                {
                    "id": "live-captures",
                    "label": "Live captures",
                    "value": int(status["liveCaptureCount"]),
                    "format": "integer",
                    "description": "Completed captures made while broadcasts were live.",
                },
                {
                    "id": "replay-captures",
                    "label": "Replay captures",
                    "value": int(status["replayCaptureCount"]),
                    "format": "integer",
                    "description": "Completed chat-replay retrievals for ended broadcasts.",
                },
                {
                    "id": "chat-actions",
                    "label": "Chat actions",
                    "value": int(status["actionCount"]),
                    "format": "integer",
                    "description": "Newline-delimited JSON actions preserved from YouTube.",
                },
                {
                    "id": "chat-messages",
                    "label": "Chat messages",
                    "value": int(status["messageCount"]),
                    "format": "integer",
                    "description": "User-authored messages represented by stored actions.",
                },
                {
                    "id": "database-size",
                    "label": "Database size",
                    "value": int(status["databaseBytes"]),
                    "format": "bytes",
                    "description": "Current on-disk size of the YT Live Chat database file.",
                },
            ]
        return plugin_status

    def handle_api(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
    ) -> tuple[int, Any] | None:
        del query
        if method == "GET" and path == "status":
            return 200, self.status()
        return None

    def shutdown(self) -> None:
        self._database_path = None
        self._config = {}


def create_plugin() -> YTLiveChatPlugin:
    return YTLiveChatPlugin()
