# YT Live Chat design

## Scope

YT Live Chat (YTLC) is an optional YT Library sidecar for preserving YouTube
live-chat actions during an active broadcast and retrieving chat replay after a
broadcast ends. The source emitted by yt-dlp is newline-delimited JSON actions
(JSONL/NDJSON), despite its `.json` filename suffix.

The initial implementation is intentionally a registration and observability
scaffold. It creates no worker process and makes no YouTube request.

## Ownership boundary

YT Library owns:

- canonical video identity and current broadcast observations;
- the shared persistent worker queue, run history, logs, stop/resume behavior,
  service capacity, and hook dispatch;
- YouTube cookie selection, validation, and safe temporary copies;
- general proxy configuration, request pacing, retry policy, and authenticated
  YouTube client/service behavior.

YTLC owns:

- chat capture and replay state;
- source JSONL artifacts and normalized chat data;
- its SQLite database, capture directory, parser, retention policy, metrics,
  API, and future browser surfaces.

The plugin config therefore contains only plugin-owned storage settings. The
plugin enable switch belongs to YT Library's Advanced Plugins configuration.

## Host video contract

The future host planning context will expose these fields:

- `video_type='livestream'` identifies livestream content. It does **not** mean
  the video is currently live.
- `broadcast_status` is `upcoming`, `live`, `ended`, an empty string, or null.
- `broadcast_started_at`, `broadcast_ended_at`, and
  `broadcast_status_checked_at` carry the corresponding observations.

Semantics are exact:

- `broadcast_status='live'` permits planning active capture.
- `broadcast_status='ended'` permits planning replay retrieval.
- null means the broadcast state has not been observed.
- an empty string means the video was confirmed not to be a broadcast.
- no broadcast state implies that chat exists or is available.

YTLC must keep its own attempted, available, unavailable, partial, failed, and
completed capture/replay state. It must not overload YT Library broadcast
fields with chat availability.

## Worker shape

Metadata scanning and chat acquisition are coupled only through enqueueing.
After a successful scan, the host hook may ask YTLC to plan a separate task for
that video. The metadata worker never downloads chat inline.

Active capture and replay retrieval will be distinct plugin worker processes.
Both will use the host's persistent queue, but they require a host-owned
YouTube service capability beyond plugin API v2's current `service: youtube`
capacity label. Acquisition remains blocked until that capability is explicit
and versioned or feature-negotiated.

## First-slice admin surface

YT Library's existing generic Advanced Plugins panel provides the YTLC
enable/disable switch. YTLC's status payload provides these zero-state metrics:

- captured videos;
- live captures;
- replay captures;
- JSONL chat actions;
- chat messages;
- database size.

The counters live in the plugin database so routine Admin polling remains a
constant-time read as the catalog grows.
