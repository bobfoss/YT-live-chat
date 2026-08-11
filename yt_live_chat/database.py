"""SQLite bootstrap and status for YT Live Chat."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1
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
        if existing_version and existing_version != SCHEMA_VERSION:
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
