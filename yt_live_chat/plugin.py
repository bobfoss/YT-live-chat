"""YT Library plugin entry point for YT Live Chat."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any
import urllib.parse

from . import __version__
from .acquisition import download_recorded_chat
from .config import config_path, ensure_config_file, load_config
from .database import (
    INTEGRATION_CONTRACT_VERSION,
    SCHEMA_VERSION,
    database_status,
    initialize_database,
    list_channel_chat_videos,
    list_video_messages,
    record_replay_observation,
    replay_states,
    store_replay_capture,
    utc_now,
    video_replay_status,
)


def _targeted_video_ids(params: dict[str, Any]) -> tuple[str, ...] | None:
    targeted = False
    requested: list[str] = []
    for name in ("video_id", "video_ids"):
        if name not in params:
            continue
        targeted = True
        raw_values = params.get(name)
        values = (
            (raw_values,)
            if isinstance(raw_values, str) or not isinstance(raw_values, Iterable)
            else raw_values
        )
        for raw_value in values:
            requested.extend(
                video_id
                for part in str(raw_value or "").split(",")
                if (video_id := part.strip())
            )
    if not targeted:
        return None
    return tuple(dict.fromkeys(requested))


def _checked_recently(value: Any, cutoff: datetime) -> bool:
    try:
        checked_at = datetime.fromisoformat(
            str(value or "").replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except ValueError:
        return False
    return checked_at >= cutoff


def _unavailable_error(message: str) -> bool:
    lowered = message.casefold()
    return any(
        marker in lowered
        for marker in (
            "members-only",
            "members only",
            "private video",
            "this video is unavailable",
            "video unavailable",
            "has been removed",
        )
    )


class YTLiveChatPlugin:
    plugin_id = "live_chat"
    plugin_name = "YT Live Chat"
    plugin_version = __version__
    plugin_api_version = 2
    required_host_features = frozenset({"youtube_ytdlp_v1"})
    capabilities = frozenset(
        {
            "video_live_chat_availability",
            "video_live_chat_messages",
            "channel_live_chat_history",
            "worker_processes",
        }
    )
    browser_assets = (
        {"path": "browser.css", "type": "style"},
        {"path": "browser.js", "type": "script"},
    )

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

    def worker_processes(self) -> tuple[dict[str, Any], ...]:
        try:
            max_in_flight = max(
                1,
                min(20, int(self._config.get("worker_max_in_flight", 2))),
            )
        except (TypeError, ValueError):
            max_in_flight = 2
        return (
            {
                "id": "replay",
                "name": "Download recorded live chat",
                "description": (
                    "Queue recorded live-chat downloads for ended livestreams "
                    "whose chat availability has not yet been observed."
                ),
                "service": "youtube",
                "maxInFlight": max_in_flight,
                "adminSurface": "advanced",
                "buttonLabel": "Download recorded live chats",
                "confirm": (
                    "Queue recorded live-chat downloads for eligible ended "
                    "livestreams? The common worker queue can be stopped and resumed."
                ),
                "hooks": ("video_scan",),
            },
        )

    def plan_worker(
        self,
        worker_id: str,
        context: Any,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if worker_id != "replay":
            raise KeyError(worker_id)
        if self._database_path is None:
            raise RuntimeError("YT Live Chat is not ready")
        requested_video_ids = _targeted_video_ids(params)
        requested = (
            frozenset(requested_video_ids)
            if requested_video_ids is not None
            else None
        )
        try:
            retry_days = max(
                0,
                min(3650, int(self._config.get("replay_retry_days", 7))),
            )
        except (TypeError, ValueError):
            retry_days = 7
        cutoff = datetime.now(timezone.utc) - timedelta(days=retry_days)
        states = replay_states(self._database_path)
        tasks: list[dict[str, Any]] = []
        for video in context.library_videos():
            video_id = str(video.get("video_id") or "").strip()
            if not video_id or (requested is not None and video_id not in requested):
                continue
            if str(video.get("video_type") or "") != "livestream":
                continue
            if str(video.get("broadcast_status") or "") != "ended":
                continue
            state = states.get(video_id) or {}
            replay_status = str(state.get("replay_status") or "")
            if replay_status == "captured":
                continue
            if replay_status and _checked_recently(
                state.get("replay_checked_at"),
                cutoff,
            ):
                continue
            tasks.append(
                {
                    "task_id": video_id,
                    "subject_id": video_id,
                    "video_id": video_id,
                    "title": str(video.get("title") or ""),
                    "priority": 0,
                    "payload": {
                        "broadcast_started_at": video.get("broadcast_started_at"),
                        "broadcast_ended_at": video.get("broadcast_ended_at"),
                        "broadcast_status_checked_at": video.get(
                            "broadcast_status_checked_at"
                        ),
                    },
                }
            )
        return tasks

    def run_worker(
        self,
        worker_id: str,
        task: dict[str, Any],
        runtime: Any,
    ) -> dict[str, Any]:
        if worker_id != "replay":
            raise KeyError(worker_id)
        if self._database_path is None:
            raise RuntimeError("YT Live Chat is not ready")
        video_id = str(task.get("video_id") or task.get("subject_id") or "").strip()
        if not video_id:
            raise ValueError("Recorded live-chat task requires a video ID")
        if runtime.stop_requested():
            return {
                "outcome": "cancelled",
                "processed": 0,
                "skipped": 1,
                "message": "Cancelled before recorded live-chat download started",
            }
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        started_at = utc_now()
        try:
            download = download_recorded_chat(
                video_id,
                config_path(self._config, "capture_directory"),
                runtime,
            )
        except Exception as exc:
            if runtime.stop_requested():
                raise
            message = f"{type(exc).__name__}: {exc}"
            replay_status = "unavailable" if _unavailable_error(message) else "failed"
            record_replay_observation(
                self._database_path,
                video_id,
                replay_status,
                message=message,
            )
            runtime.log("warn" if replay_status == "unavailable" else "error", message)
            return {
                "outcome": replay_status,
                "processed": 1,
                "failed": 0 if replay_status == "unavailable" else 1,
                "skipped": 1 if replay_status == "unavailable" else 0,
                "message": message,
            }
        if download.status == "not_available":
            message = f"No recorded live chat is currently available for {video_id}"
            record_replay_observation(
                self._database_path,
                video_id,
                "not_available",
                message=message,
            )
            runtime.log("warn", message)
            return {
                "outcome": "not_available",
                "processed": 1,
                "skipped": 1,
                "message": message,
            }
        if download.parsed is None:
            raise RuntimeError("Recorded live-chat download has no parsed actions")
        stored = store_replay_capture(
            self._database_path,
            video_id,
            source_path=download.source_path,
            source_sha256=download.source_sha256,
            source_bytes=download.source_bytes,
            yt_dlp_version=download.yt_dlp_version,
            parsed=download.parsed,
            started_at=started_at,
            broadcast_started_at=payload.get("broadcast_started_at"),
            broadcast_ended_at=payload.get("broadcast_ended_at"),
            broadcast_status_checked_at=payload.get(
                "broadcast_status_checked_at"
            ),
        )
        action_count = len(download.parsed.actions)
        message_count = download.parsed.message_count
        message = (
            f"Downloaded {action_count} chat action(s) and {message_count} "
            f"message(s) for {video_id}"
        )
        if not stored["created"]:
            message += "; capture content was already stored"
        runtime.log("info", message)
        return {
            "outcome": "found",
            "processed": 1,
            "found": 1,
            "message": message,
        }

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
                    "label": "Recorded chats",
                    "value": int(status["replayCaptureCount"]),
                    "format": "integer",
                    "description": "Recorded live chats downloaded after broadcasts ended.",
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
                    "id": "unique-channels",
                    "label": "Unique channels",
                    "value": int(status["uniqueChannelCount"]),
                    "format": "integer",
                    "description": (
                        "Distinct author channel IDs represented by stored chat messages."
                    ),
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
        if method == "GET" and path == "status":
            return 200, self.status()
        if method == "GET" and path == "videos":
            if self._database_path is None:
                return 503, {"error": "YT Live Chat is not ready"}
            try:
                return 200, {
                    "videos": video_replay_status(
                        self._database_path,
                        query.get("id") or [],
                    )
                }
            except ValueError as exc:
                return 400, {"error": str(exc)}
        messages_match = re.fullmatch(r"videos/([^/]+)/messages", path)
        if method == "GET" and messages_match:
            if self._database_path is None:
                return 503, {"error": "YT Live Chat is not ready"}
            video_id = urllib.parse.unquote(messages_match.group(1))
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return 400, {"error": "Expected an 11-character YouTube video ID"}
            try:
                limit = int((query.get("limit") or ["250"])[0] or 250)
                offset = int((query.get("offset") or ["0"])[0] or 0)
                return 200, list_video_messages(
                    self._database_path,
                    video_id,
                    limit=limit,
                    offset=offset,
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}
        channel_videos_match = re.fullmatch(r"channels/([^/]+)/videos", path)
        if method == "GET" and channel_videos_match:
            if self._database_path is None:
                return 503, {"error": "YT Live Chat is not ready"}
            author_channel_id = urllib.parse.unquote(channel_videos_match.group(1))
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", author_channel_id):
                return 400, {"error": "Expected a YouTube author channel ID"}
            try:
                limit = int((query.get("limit") or ["100"])[0] or 100)
                offset = int((query.get("offset") or ["0"])[0] or 0)
                return 200, list_channel_chat_videos(
                    self._database_path,
                    author_channel_id,
                    limit=limit,
                    offset=offset,
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}
        return None

    def handle_browser_asset(self, path: str) -> tuple[str, bytes]:
        content_types = {
            "browser.css": "text/css; charset=utf-8",
            "browser.js": "text/javascript; charset=utf-8",
        }
        if path not in content_types:
            raise KeyError(path)
        return content_types[path], Path(__file__).with_name(path).read_bytes()

    def shutdown(self) -> None:
        self._database_path = None
        self._config = {}


def create_plugin() -> YTLiveChatPlugin:
    return YTLiveChatPlugin()
