"""Parse yt-dlp's newline-delimited YouTube live-chat actions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MESSAGE_RENDERERS = frozenset(
    {
        "liveChatMembershipItemRenderer",
        "liveChatPaidMessageRenderer",
        "liveChatPaidStickerRenderer",
        "liveChatTextMessageRenderer",
    }
)


@dataclass(frozen=True)
class ChatAction:
    sequence: int
    video_offset_ms: int | None
    action_type: str
    renderer_type: str
    message_id: str
    author_channel_id: str
    author_name: str
    message_text: str
    is_message: bool
    payload_json: str


@dataclass(frozen=True)
class ParsedChatReplay:
    source_line_count: int
    actions: tuple[ChatAction, ...]
    message_count: int
    author_count: int
    first_offset_ms: int | None
    last_offset_ms: int | None


def _text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    simple = str(value.get("simpleText") or "")
    if simple:
        return simple
    parts: list[str] = []
    for run in value.get("runs") or []:
        if not isinstance(run, dict):
            continue
        text = str(run.get("text") or "")
        if text:
            parts.append(text)
            continue
        emoji = run.get("emoji")
        if not isinstance(emoji, dict):
            continue
        shortcuts = emoji.get("shortcuts") or []
        token = str(shortcuts[0]) if shortcuts else str(emoji.get("emojiId") or "")
        if token:
            parts.append(token)
    return "".join(parts)


def _renderer(action_type: str, action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = action.get(action_type)
    if not isinstance(payload, dict):
        return "", {}
    for field in ("item", "replacementItem"):
        item = payload.get(field)
        if not isinstance(item, dict):
            continue
        for renderer_type, renderer in item.items():
            if renderer_type.endswith("Renderer") and isinstance(renderer, dict):
                return renderer_type, renderer
    return "", {}


def _offset(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_chat_jsonl(path: Path | str) -> ParsedChatReplay:
    source = Path(path)
    actions: list[ChatAction] = []
    authors: set[str] = set()
    offsets: list[int] = []
    source_line_count = 0
    for line_number, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        source_line_count += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid live-chat JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Live-chat JSONL line {line_number} is not an object")
        replay = row.get("replayChatItemAction")
        replay = replay if isinstance(replay, dict) else {}
        video_offset_ms = _offset(replay.get("videoOffsetTimeMsec"))
        embedded = replay.get("actions")
        embedded_actions = (
            [value for value in embedded if isinstance(value, dict)]
            if isinstance(embedded, list)
            else []
        )
        if not embedded_actions:
            embedded_actions = [row]
        for raw_action in embedded_actions:
            action_type = next(
                (
                    str(key)
                    for key in raw_action
                    if key != "clickTrackingParams"
                ),
                next(iter(raw_action), "unknownAction"),
            )
            renderer_type, renderer = _renderer(action_type, raw_action)
            author_channel_id = str(
                renderer.get("authorExternalChannelId") or ""
            ).strip()
            author_name = _text(renderer.get("authorName"))
            message_text = _text(renderer.get("message"))
            message_id = str(renderer.get("id") or "").strip()
            is_message = bool(author_channel_id) or renderer_type in MESSAGE_RENDERERS
            if author_channel_id:
                authors.add(author_channel_id)
            if video_offset_ms is not None:
                offsets.append(video_offset_ms)
            actions.append(
                ChatAction(
                    sequence=len(actions),
                    video_offset_ms=video_offset_ms,
                    action_type=action_type,
                    renderer_type=renderer_type,
                    message_id=message_id,
                    author_channel_id=author_channel_id,
                    author_name=author_name,
                    message_text=message_text,
                    is_message=is_message,
                    payload_json=json.dumps(
                        raw_action,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
    return ParsedChatReplay(
        source_line_count=source_line_count,
        actions=tuple(actions),
        message_count=sum(action.is_message for action in actions),
        author_count=len(authors),
        first_offset_ms=min(offsets) if offsets else None,
        last_offset_ms=max(offsets) if offsets else None,
    )
