# YT Live Chat

YT Live Chat is an optional sidecar plugin for YT Library. The informal project
name is **YTLC**.

YTLC downloads recorded live chat for ended livestreams through YT Library's
host-owned YouTube service. It preserves the source as JSONL, normalizes actions
into its own SQLite database, and reports capture statistics in YT Library's
Advanced Plugins panel. YT Library retains ownership of cookies, proxy policy,
request pacing, retries, logging, cancellation, and the persistent worker queue.

Captured videos receive a **Recorded chat** indicator throughout YT Library's
native video views. Their video detail page includes a collapsible, bounded
message viewport that loads 100-message pages as the viewer approaches the end
of the current window. Its search covers the complete captured chat with
indexed prefix matching, so `burn` also matches `burning`; search remains local
to the open recorded-chat panel and is deliberately excluded from YT Library's
omni search. Timestamp links open the YouTube video at each message's recorded
offset. Chat author names link to their local YTL channel entry, using the
captured `@handle` in the local URL, when the captured author channel ID is
present in the library. The viewer does not yet synchronize with an embedded
player.

Channel detail pages also receive a **Chat history** tab. It lists canonical
YTL videos whose latest captured chat contains messages from that channel,
ordered by the recorded broadcast end time.

## Install for local development

From this repository:

```powershell
& "..\YT Library\.venv\Scripts\python.exe" -m pip install -e .
```

Then register it in YT Library's local `yt_library.config.json`:

```json
{
  "plugins": {
    "live_chat": {
      "name": "YT Live Chat",
      "enabled": true,
      "config": "../YT Live Chat/yt_live_chat.config.json"
    }
  }
}
```

On first start, YTLC creates or upgrades its config and database. YT Library
owns the enable/disable control. When enabled, the Advanced Plugins panel shows
the plugin status, a **Download recorded live chats** action, queue/run state,
and capture statistics. Successful metadata scans enqueue a separate YTLC task
only when `video_type='livestream'` and `broadcast_status='ended'`.

See [docs/design.md](docs/design.md) for the agreed host boundary and future
worker shape.
