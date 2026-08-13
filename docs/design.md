# YT Live Chat design

## Scope

YT Live Chat (YTLC) is an optional YT Library sidecar for preserving YouTube
live-chat actions during an active broadcast and retrieving chat replay after a
broadcast ends. The source emitted by yt-dlp is newline-delimited JSON actions
(JSONL/NDJSON), despite its `.json` filename suffix.

The recorded-chat implementation provides a bounded worker for ended
livestreams plus a native-card availability indicator and paginated video-detail
message viewer. Active-broadcast capture, synchronized playback, and chat search
remain later milestones.

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

Active capture and recorded-chat retrieval are distinct plugin worker
processes. The implemented `replay` process requires the feature-negotiated
`youtube_ytdlp_v1` service. YTL supplies disposable cookies, proxy and request
policy, logging, retry limits, and cancellation. YTLC supplies the video ID,
the live-chat artifact options, and its plugin-owned staging destination.

The recorded-chat planner accepts only `video_type='livestream'` with
`broadcast_status='ended'`. It subscribes to `video_scan`, and its Advanced
bulk action plans eligible existing rows. Its internal states are `captured`,
`not_available`, `unavailable`, and `failed`, each with an observation time.
Recent negative observations are not immediately retried; none are inferred
from broadcast state.

yt-dlp output is validated as JSONL before it is atomically moved to a
content-addressed `.jsonl` artifact. YTLC stores immutable capture revisions
and normalized action rows containing offsets, action and renderer types,
message/author fields, and the preserved raw action payload. Repeating an
identical download reuses the source hash and does not duplicate actions or
statistics.

The browser integration is plugin-owned. It uses YT Library's generic
`entityCards` and `videoDetail` contracts, queries at most 500 video identities
per availability request, and retrieves at most 500 user messages per page.

YTLC advertises the `channel_live_chat_history` capability and contributes a
browser `channelVideoTabs` entry. Its count and page requests query only the
latest capture associated with each video, group matching message actions by
canonical author channel ID, and return bounded video IDs to the host. YTL
hydrates and renders those IDs as native cards; YTLC never reads the YTL
database.
Timestamp links open the source video at the recorded offset; they are not an
embedded-player synchronization contract.

## First-slice admin surface

YT Library's existing generic Advanced Plugins panel provides the YTLC
enable/disable switch. YTLC's status payload provides these zero-state metrics:

- captured videos;
- live captures;
- recorded chats;
- JSONL chat actions;
- chat messages;
- database size.

The counters live in the plugin database so routine Admin polling remains a
constant-time read as the catalog grows.
