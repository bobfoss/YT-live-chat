"""Current-capture search and collection cards, owned entirely by YTLC."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from .database import _fts_query, connect


ALL_AUTHORS = (True, True, "")


def _author_condition(authors: tuple[bool, bool, str]) -> tuple[str, tuple[str, ...]]:
    own, others, channel_id = authors
    if own and others:
        return "1", ()
    if not own and not others:
        return "0", ()
    if not channel_id:
        raise RuntimeError("YouTube account identity is required to filter chat authors")
    return f"a.author_channel_id <> '' AND a.author_channel_id {'=' if own else '<>'} ?", (channel_id,)


def catalog_count(db_path: Path | str) -> int:
    conn = connect(db_path, read_only=True)
    try:
        return int(conn.execute("""
            SELECT COUNT(*) FROM chat_targets t
            JOIN chat_captures c ON c.capture_id=t.latest_capture_id
            WHERE t.replay_status='captured'
        """).fetchone()[0])
    finally:
        conn.close()


def _current_captures(db_path: Path | str) -> list[dict[str, Any]]:
    conn = connect(db_path, read_only=True)
    try:
        return [dict(row) for row in conn.execute("""
            SELECT t.video_id, c.capture_id, c.message_count, c.author_count,
                   c.status, c.completed_at, c.broadcast_started_at, c.broadcast_ended_at
            FROM chat_targets t JOIN chat_captures c ON c.capture_id=t.latest_capture_id
            WHERE t.replay_status='captured' ORDER BY t.video_id
        """)]
    finally:
        conn.close()


@lru_cache(maxsize=32)
def _matching_captures(
    db_path: str, current_ids: tuple[int, ...], match_query: str,
    authors: tuple[bool, bool, str],
) -> frozenset[int]:
    # Capture revisions are immutable. The current-ID tuple invalidates this
    # bounded cache even when several acquisitions finish in the same second.
    conn = connect(db_path, read_only=True)
    try:
        current = frozenset(current_ids)
        author_sql, author_params = _author_condition(authors)
        if not match_query:
            return frozenset(int(row[0]) for row in conn.execute(f"""
                SELECT t.latest_capture_id FROM chat_targets t
                WHERE t.replay_status='captured' AND EXISTS (
                    SELECT 1 FROM chat_actions a
                    WHERE a.capture_id=t.latest_capture_id AND a.is_message=1 AND {author_sql}
                )
            """, author_params) if int(row[0]) in current)
        return frozenset(
            int(row[0]) for row in conn.execute(f"""
                SELECT DISTINCT a.capture_id
                FROM chat_message_search_fts
                JOIN chat_actions a ON a.rowid=chat_message_search_fts.rowid
                WHERE chat_message_search_fts MATCH ? AND a.is_message=1 AND {author_sql}
            """, (f"message_text : ({match_query})", *author_params))
            if int(row[0]) in current
        )
    finally:
        conn.close()


@lru_cache(maxsize=32)
def _presence(video_ids: tuple[str, ...]) -> frozenset[str]:
    return frozenset(video_ids)


def _matched_rows(
    db_path: Path | str, rows: list[dict[str, Any]], query: str,
    authors: tuple[bool, bool, str] = ALL_AUTHORS,
) -> list[dict[str, Any]]:
    if not any(authors[:2]):
        return []
    if not query.strip() and all(authors[:2]):
        return rows
    try:
        match_query = _fts_query(query) if query.strip() else ""
    except ValueError:
        return []
    matches = _matching_captures(
        str(Path(db_path).resolve()), tuple(row["capture_id"] for row in rows), match_query, authors,
    )
    return [row for row in rows if row["capture_id"] in matches]


def filter_videos(
    db_path: Path | str, query: str, authors: tuple[bool, bool, str] = ALL_AUTHORS,
) -> dict[str, frozenset[str]]:
    rows = _current_captures(db_path)
    return {
        "video_ids": _presence(tuple(row["video_id"] for row in rows)),
        "search_match_ids": frozenset(
            row["video_id"] for row in _matched_rows(db_path, rows, query, authors)
        ) if query.strip() else frozenset(),
    }


def descriptors(
    db_path: Path | str, query: str,
    library_videos: Callable[[Iterable[str]], Iterable[dict[str, Any]]],
    *, browse: bool = False, authors: tuple[bool, bool, str] = ALL_AUTHORS,
) -> list[dict[str, Any]]:
    if not query.strip() and not browse:
        return []
    rows = _current_captures(db_path)
    rows = _matched_rows(db_path, rows, query, authors)
    titles: dict[str, str] = {}
    for start in range(0, len(rows), 500):
        titles.update((video["video_id"], str(video.get("title") or ""))
                      for video in library_videos([row["video_id"] for row in rows[start:start + 500]]))
    return [{
        "id": f"chat:{row['video_id']}", "video_id": row["video_id"],
        "title": titles.get(row["video_id"], ""),
        "newest_at": row["broadcast_ended_at"] or row["broadcast_started_at"] or row["completed_at"],
        "oldest_at": row["broadcast_started_at"] or row["broadcast_ended_at"] or row["completed_at"],
        "like_count": None,
    } for row in rows]


def hydrate(
    db_path: Path | str, ids: list[str], query: str,
    authors: tuple[bool, bool, str] = ALL_AUTHORS,
) -> dict[str, dict[str, Any]]:
    requested = list(dict.fromkeys(ids))
    if not requested:
        return {}
    if len(requested) > 5000:
        raise ValueError("At most 5000 chat cards may be requested")
    if not any(authors[:2]):
        return {}
    author_sql, author_params = _author_condition(authors)
    match_query = ""
    if query.strip():
        try:
            match_query = _fts_query(query)
        except ValueError:
            return {}
    conn = connect(db_path, read_only=True)
    try:
        conn.execute("BEGIN")
        results = {}
        for key in requested:
            if not key.startswith("chat:"):
                continue
            row = conn.execute("""
                SELECT t.video_id, c.capture_id, c.message_count, c.author_count,
                       c.status, c.completed_at, c.broadcast_started_at, c.broadcast_ended_at
                FROM chat_targets t JOIN chat_captures c ON c.capture_id=t.latest_capture_id
                WHERE t.video_id=? AND t.replay_status='captured'
            """, (key[5:],)).fetchone()
            if row is None:
                continue
            params: tuple[Any, ...] = (row["capture_id"],)
            source = "chat_actions a"
            condition = "a.capture_id=? AND a.is_message=1"
            snippet = "substr(a.message_text,1,300)"
            if match_query:
                source = "chat_message_search_fts JOIN chat_actions a ON a.rowid=chat_message_search_fts.rowid"
                condition += " AND chat_message_search_fts MATCH ?"
                params += (f'capture_id : "{row["capture_id"]}" AND message_text : ({match_query})',)
                snippet = "snippet(chat_message_search_fts,1,'<mark>','</mark>','…',36)"
            condition += f" AND {author_sql}"
            params += author_params
            messages = [dict(message) for message in conn.execute(f"""
                SELECT a.sequence, a.video_offset_ms AS offsetMs,
                       a.author_channel_id AS authorChannelId, a.author_name AS authorName,
                       substr(a.message_text,1,300) AS messageText, {snippet} AS snippet
                FROM {source} WHERE {condition} ORDER BY a.sequence LIMIT 3
            """, params)]
            if (match_query or not all(authors[:2])) and not messages:
                continue
            results[key] = {**dict(row), "id": key, "messages": messages, "query": query.strip()}
        return results
    finally:
        conn.close()


def collection(
    db_path: Path | str, query: str, limit: int, offset: int, sort: str,
    library_videos: Callable[[Iterable[str]], Iterable[dict[str, Any]]],
    authors: tuple[bool, bool, str] = ALL_AUTHORS,
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ValueError("Chat limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("Chat offset must be nonnegative")
    if sort not in {"newest", "oldest"}:
        raise ValueError("Unknown live chat order")
    rows = descriptors(db_path, query, library_videos, browse=True, authors=authors)
    rows.sort(key=lambda row: row["id"])
    rows.sort(key=lambda row: row[f'{sort}_at'] or "", reverse=sort == "newest")
    offset = min(offset, max(0, (len(rows) - 1) // limit) * limit)
    page = rows[offset:offset + limit]
    items = hydrate(db_path, [row["id"] for row in page], query, authors)
    return {
        "total": len(rows), "totalIsExact": True, "limit": limit, "offset": offset,
        "results": [{**items[row["id"]], "title": row["title"]} for row in page if row["id"] in items],
    }
