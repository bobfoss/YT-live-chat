"""Recorded live-chat acquisition through YT Library's YouTube service."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonl import ParsedChatReplay, parse_chat_jsonl


@dataclass(frozen=True)
class ReplayDownload:
    status: str
    source_path: str = ""
    source_sha256: str = ""
    source_bytes: int = 0
    yt_dlp_version: str = ""
    parsed: ParsedChatReplay | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_recorded_chat(
    video_id: str,
    capture_directory: Path | str,
    runtime: Any,
) -> ReplayDownload:
    capture_root = Path(capture_directory).resolve()
    staging_root = capture_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{video_id}-", dir=staging_root) as temp_dir:
        output_template = str(Path(temp_dir) / "%(id)s.%(ext)s")
        info = runtime.run_youtube_ytdlp(
            video_id,
            {
                "outtmpl": output_template,
                "skip_download": True,
                "subtitlesformat": "json",
                "subtitleslangs": ["live_chat"],
                "writesubtitles": True,
            },
            download=True,
        )
        candidates = sorted(Path(temp_dir).glob("*.live_chat.json"))
        if not candidates:
            subtitles = info.get("subtitles") or {}
            if not isinstance(subtitles, dict) or not subtitles.get("live_chat"):
                return ReplayDownload(status="not_available")
            raise RuntimeError("yt-dlp advertised recorded live chat but wrote no JSONL")
        source = candidates[0]
        parsed = parse_chat_jsonl(source)
        source_sha256 = _sha256(source)
        destination_dir = capture_root / video_id[:2] / video_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"replay-{source_sha256}.jsonl"
        if destination.exists():
            source.unlink()
        else:
            os.replace(source, destination)
        try:
            yt_dlp_version = importlib.metadata.version("yt-dlp")
        except importlib.metadata.PackageNotFoundError:
            yt_dlp_version = ""
        return ReplayDownload(
            status="captured",
            source_path=destination.relative_to(capture_root).as_posix(),
            source_sha256=source_sha256,
            source_bytes=destination.stat().st_size,
            yt_dlp_version=yt_dlp_version,
            parsed=parsed,
        )
