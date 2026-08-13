"""SQLite bootstrap and status for YT Live Chat."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonl import ParsedChatReplay


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2
INTEGRATION_CONTRACT_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def connect(db_path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if read_only:
        if not path.is_file():
            raise FileNotFoundError(f"Live chat database not found: {path}")
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", timeout=60, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA foreign_keys = ON")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    else:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "sidecar_metadata"):
        return 0
    row = conn.execute(
        "SELECT value FROM sidecar_metadata WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _has_application_tables(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            LIMIT 1
            """
        ).fetchone()
        is not None
    )


def initialize_database(db_path: Path | str) -> Path:
    path = Path(db_path).resolve()
    conn = connect(path)
    try:
        existing_version = _schema_version(conn)
        if existing_version not in {0, 1, SCHEMA_VERSION}:
            raise RuntimeError(
                "Live chat database uses alpha schema "
                f"{existing_version}; rebuild it for schema {SCHEMA_VERSION}"
            )
        if existing_version == 0 and _has_application_tables(conn):
            raise RuntimeError(
                "Live chat database contains an unversioned schema; rebuild it before use"
            )
        with conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO sidecar_metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO sidecar_metadata(key, value) VALUES (?, ?)",
                ("integration_contract_version", str(INTEGRATION_CONTRACT_VERSION)),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO catalog_stats(singleton, updated_at)
                VALUES (1, ?)
                """,
                (utc_now(),),
            )
    finally:
        conn.close()
    return path


def database_status(db_path: Path | str) -> dict[str, Any]:
    path = Path(db_path).resolve()
    if not path.is_file():
        return {
            "available": False,
            "compatible": False,
            "path": str(path),
            "message": "Live chat database has not been initialized",
        }
    conn: sqlite3.Connection | None = None
    try:
        conn = connect(path, read_only=True)
        schema_version = _schema_version(conn)
        contract_row = (
            conn.execute(
                """
                SELECT value
                FROM sidecar_metadata
                WHERE key = 'integration_contract_version'
                """
            ).fetchone()
            if _table_exists(conn, "sidecar_metadata")
            else None
        )
        contract_version = int(contract_row[0]) if contract_row else 0
        compatible = (
            schema_version == SCHEMA_VERSION
            and contract_version == INTEGRATION_CONTRACT_VERSION
        )
        status: dict[str, Any] = {
            "available": True,
            "compatible": compatible,
            "path": str(path),
            "databaseBytes": path.stat().st_size,
            "schemaVersion": schema_version,
            "integrationContractVersion": contract_version,
        }
        if not compatible:
            status["message"] = (
                f"Schema {schema_version} and integration contract {contract_version} "
                f"must match {SCHEMA_VERSION} and {INTEGRATION_CONTRACT_VERSION}"
            )
            return status
        stats = conn.execute(
            "SELECT * FROM catalog_stats WHERE singleton = 1"
        ).fetchone()
        if stats is None:
            raise RuntimeError("Live chat catalog statistics are missing")
        status.update(
            {
                "capturedVideoCount": int(stats["captured_video_count"]),
                "liveCaptureCount": int(stats["live_capture_count"]),
                "replayCaptureCount": int(stats["replay_capture_count"]),
                "actionCount": int(stats["action_count"]),
                "messageCount": int(stats["message_count"]),
                "sourceBytes": int(stats["source_byte_count"]),
                "statsUpdatedAt": str(stats["updated_at"]),
            }
        )
        return status
    except (OSError, sqlite3.Error, TypeError, ValueError, RuntimeError) as exc:
        return {
            "available": False,
            "compatible": False,
            "path": str(path),
            "message": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if conn is not None:
            conn.close()


def _refresh_catalog_stats(conn: sqlite3.Connection, now: str) -> None:
    conn.execute(
        """
        UPDATE catalog_stats
        SET captured_video_count = (
              SELECT COUNT(DISTINCT video_id) FROM chat_captures
              WHERE status = 'complete'
            ),
            live_capture_count = (
              SELECT COUNT(*) FROM chat_captures
              WHERE status = 'complete' AND mode = 'live'
            ),
            replay_capture_count = (
              SELECT COUNT(*) FROM chat_captures
              WHERE status = 'complete' AND mode = 'replay'
            ),
            action_count = (SELECT COUNT(*) FROM chat_actions),
            message_count = (
              SELECT COALESCE(SUM(is_message), 0) FROM chat_actions
            ),
            source_byte_count = (
              SELECT COALESCE(SUM(source_bytes), 0) FROM chat_captures
              WHERE status = 'complete'
            ),
            updated_at = ?
        WHERE singleton = 1
        """,
        (now,),
    )


def replay_states(db_path: Path | str) -> dict[str, dict[str, Any]]:
    conn = connect(db_path, read_only=True)
    try:
        return {
            str(row["video_id"]): dict(row)
            for row in conn.execute(
                """
                SELECT video_id, replay_status, replay_checked_at,
                       latest_capture_id, last_error
                FROM chat_targets
                ORDER BY video_id
                """
            )
        }
    finally:
        conn.close()


def record_replay_observation(
    db_path: Path | str,
    video_id: str,
    replay_status: str,
    *,
    message: str = "",
) -> None:
    if replay_status not in {"not_available", "unavailable", "failed"}:
        raise ValueError(f"Invalid replay observation status: {replay_status}")
    now = utc_now()
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO chat_targets(
                  video_id, replay_status, replay_checked_at,
                  latest_capture_id, last_error, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  replay_status = excluded.replay_status,
                  replay_checked_at = excluded.replay_checked_at,
                  last_error = excluded.last_error,
                  updated_at = excluded.updated_at
                """,
                (video_id, replay_status, now, str(message or "")[:10_000], now),
            )
    finally:
        conn.close()


def store_replay_capture(
    db_path: Path | str,
    video_id: str,
    *,
    source_path: str,
    source_sha256: str,
    source_bytes: int,
    yt_dlp_version: str,
    parsed: ParsedChatReplay,
    started_at: str,
    broadcast_started_at: str | None,
    broadcast_ended_at: str | None,
    broadcast_status_checked_at: str | None,
) -> dict[str, Any]:
    completed_at = utc_now()
    conn = connect(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO chat_captures(
                  video_id, mode, status, source_path, source_sha256,
                  source_bytes, source_line_count, action_count, message_count,
                  author_count, first_offset_ms, last_offset_ms,
                  broadcast_started_at, broadcast_ended_at,
                  broadcast_status_checked_at, yt_dlp_version,
                  started_at, completed_at
                )
                VALUES (?, 'replay', 'complete', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    source_path,
                    source_sha256,
                    max(0, int(source_bytes)),
                    parsed.source_line_count,
                    len(parsed.actions),
                    parsed.message_count,
                    parsed.author_count,
                    parsed.first_offset_ms,
                    parsed.last_offset_ms,
                    broadcast_started_at,
                    broadcast_ended_at,
                    broadcast_status_checked_at,
                    str(yt_dlp_version or ""),
                    started_at,
                    completed_at,
                ),
            )
            created = bool(cursor.rowcount)
            if created:
                capture_id = int(cursor.lastrowid)
                conn.executemany(
                    """
                    INSERT INTO chat_actions(
                      capture_id, sequence, video_offset_ms, action_type,
                      renderer_type, message_id, author_channel_id, author_name,
                      message_text, is_message, payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            capture_id,
                            action.sequence,
                            action.video_offset_ms,
                            action.action_type,
                            action.renderer_type,
                            action.message_id,
                            action.author_channel_id,
                            action.author_name,
                            action.message_text,
                            1 if action.is_message else 0,
                            action.payload_json,
                        )
                        for action in parsed.actions
                    ),
                )
            else:
                row = conn.execute(
                    """
                    SELECT capture_id
                    FROM chat_captures
                    WHERE video_id = ? AND mode = 'replay' AND source_sha256 = ?
                    """,
                    (video_id, source_sha256),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Stored replay capture could not be reloaded")
                capture_id = int(row["capture_id"])
            conn.execute(
                """
                INSERT INTO chat_targets(
                  video_id, replay_status, replay_checked_at,
                  latest_capture_id, last_error, updated_at
                )
                VALUES (?, 'captured', ?, ?, '', ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  replay_status = 'captured',
                  replay_checked_at = excluded.replay_checked_at,
                  latest_capture_id = excluded.latest_capture_id,
                  last_error = '',
                  updated_at = excluded.updated_at
                """,
                (video_id, completed_at, capture_id, completed_at),
            )
            _refresh_catalog_stats(conn, completed_at)
        return {"captureId": capture_id, "created": created}
    finally:
        conn.close()


def video_replay_status(
    db_path: Path | str,
    video_ids: list[str] | tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    normalized = tuple(dict.fromkeys(str(value or "").strip() for value in video_ids))
    normalized = tuple(value for value in normalized if value)
    if len(normalized) > 500:
        raise ValueError("At most 500 video IDs may be requested")
    if not normalized:
        return {}
    placeholders = ",".join("?" for _value in normalized)
    conn = connect(db_path, read_only=True)
    try:
        rows = {
            str(row["video_id"]): dict(row)
            for row in conn.execute(
                f"""
                SELECT t.video_id, t.replay_status, t.replay_checked_at,
                       t.last_error, c.capture_id, c.source_bytes,
                       c.action_count, c.message_count, c.author_count,
                       c.first_offset_ms, c.last_offset_ms, c.completed_at
                FROM chat_targets t
                LEFT JOIN chat_captures c ON c.capture_id = t.latest_capture_id
                WHERE t.video_id IN ({placeholders})
                """,
                normalized,
            )
        }
    finally:
        conn.close()
    return {
        video_id: rows.get(
            video_id,
            {
                "video_id": video_id,
                "replay_status": "unobserved",
                "replay_checked_at": "",
                "last_error": "",
                "capture_id": None,
            },
        )
        for video_id in normalized
    }


def list_video_messages(
    db_path: Path | str,
    video_id: str,
    *,
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_video_id = str(video_id or "").strip()
    if not normalized_video_id:
        raise ValueError("Video ID is required")
    if limit < 1 or limit > 500:
        raise ValueError("Message limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("Message offset must be nonnegative")
    conn = connect(db_path, read_only=True)
    try:
        capture = conn.execute(
            """
            SELECT c.capture_id, c.completed_at
            FROM chat_targets t
            JOIN chat_captures c ON c.capture_id = t.latest_capture_id
            WHERE t.video_id = ? AND t.replay_status = 'captured'
            """,
            (normalized_video_id,),
        ).fetchone()
        if capture is None:
            return {
                "videoId": normalized_video_id,
                "captureId": None,
                "completedAt": "",
                "total": 0,
                "limit": limit,
                "offset": offset,
                "messages": [],
            }
        capture_id = int(capture["capture_id"])
        total = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM chat_actions
                WHERE capture_id = ? AND is_message = 1
                """,
                (capture_id,),
            ).fetchone()[0]
        )
        messages = [
            {
                "sequence": int(row["sequence"]),
                "offsetMs": row["video_offset_ms"],
                "actionType": str(row["action_type"]),
                "rendererType": str(row["renderer_type"]),
                "messageId": str(row["message_id"]),
                "authorChannelId": str(row["author_channel_id"]),
                "authorName": str(row["author_name"]),
                "messageText": str(row["message_text"]),
            }
            for row in conn.execute(
                """
                SELECT sequence, video_offset_ms, action_type, renderer_type,
                       message_id, author_channel_id, author_name, message_text
                FROM chat_actions
                WHERE capture_id = ? AND is_message = 1
                ORDER BY sequence
                LIMIT ? OFFSET ?
                """,
                (capture_id, limit, offset),
            )
        ]
        return {
            "videoId": normalized_video_id,
            "captureId": capture_id,
            "completedAt": str(capture["completed_at"]),
            "total": total,
            "limit": limit,
            "offset": offset,
            "messages": messages,
        }
    finally:
        conn.close()


def list_channel_chat_videos(
    db_path: Path | str,
    author_channel_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_channel_id = str(author_channel_id or "").strip()
    if not normalized_channel_id:
        raise ValueError("Author channel ID is required")
    if limit < 1 or limit > 500:
        raise ValueError("Video limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("Video offset must be nonnegative")
    conn = connect(db_path, read_only=True)
    try:
        total = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT t.video_id)
                FROM chat_targets t
                JOIN chat_captures c ON c.capture_id = t.latest_capture_id
                JOIN chat_actions a ON a.capture_id = c.capture_id
                WHERE t.replay_status = 'captured'
                  AND a.is_message = 1
                  AND a.author_channel_id = ?
                """,
                (normalized_channel_id,),
            ).fetchone()[0]
        )
        if total and offset >= total:
            offset = ((total - 1) // limit) * limit
        videos = [
            {
                "videoId": str(row["video_id"]),
                "messageCount": int(row["message_count"]),
                "firstOffsetMs": row["first_offset_ms"],
                "lastOffsetMs": row["last_offset_ms"],
                "participatedAt": str(row["participated_at"] or ""),
            }
            for row in conn.execute(
                """
                SELECT t.video_id,
                       COUNT(*) AS message_count,
                       MIN(a.video_offset_ms) AS first_offset_ms,
                       MAX(a.video_offset_ms) AS last_offset_ms,
                       COALESCE(c.broadcast_ended_at, c.completed_at) AS participated_at
                FROM chat_targets t
                JOIN chat_captures c ON c.capture_id = t.latest_capture_id
                JOIN chat_actions a ON a.capture_id = c.capture_id
                WHERE t.replay_status = 'captured'
                  AND a.is_message = 1
                  AND a.author_channel_id = ?
                GROUP BY t.video_id, c.broadcast_ended_at, c.completed_at
                ORDER BY participated_at DESC, t.video_id
                LIMIT ? OFFSET ?
                """,
                (normalized_channel_id, limit, offset),
            )
        ]
        return {
            "authorChannelId": normalized_channel_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "videos": videos,
        }
    finally:
        conn.close()
