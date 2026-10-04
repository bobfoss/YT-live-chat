# YT Live Chat

Licensed under the GNU General Public License, version 3 or (at your option)
any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE). Distributed
without any warranty; see the license for details. Third-party dependencies
retain their own licenses.

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
indexed prefix matching, so `burn` also matches `burning`. The same matching
also participates in YT Library's global search through **Search in → Live chats**
and the **live chats / no live chats** video facet. Timestamp links open the YouTube video at each message's recorded
offset. Chat author names link to their local YTL channel entry, using the
captured `@handle` in the local URL, when the captured author channel ID is
present in the library. The viewer does not yet synchronize with an embedded
player.

Channel detail pages also receive a **Chat history** tab. It lists canonical
YTL videos whose latest captured chat contains messages from that channel,
ordered by the recorded broadcast end time. Channel history queries begin with
the indexed author rows, so unrelated actions in large captured chats are not
scanned to calculate the tab count or video page.

**Meta → Live chats** at `/live_chat` browses current captured chats, including
with a blank query, and searches only chat message text. It shares YTL's Meta
navigation with other enabled plugins and works independently of YT Comments.
Global chat cards require a nonblank matching query and share native sorting,
filters, and pagination. Each card represents one video's current capture and
shows up to three message excerpts with timestamp and known-author links.
Newest uses broadcast end (then start); Oldest uses broadcast start (then end).
Missing broadcast timestamps fall back to the capture time, labelled Captured.
Like counts are unknown. Superseded captures and system actions do not match.
Indexed matches use a bounded memory cache invalidated by current capture IDs;
no schema rebuild or library rescan is required.

The **own** and **others** checkboxes beside the shared result controls filter
message matches and excerpts, both on the collection and in global search.
Both start checked (all authors); neither checked returns no chat cards. A chat
can qualify for both groups. “Own” means the active channel authenticated by
YTL's configured YouTube cookie, resolved by the host from YouTube account
settings—not a manually entered handle or a YT Comments identity. The host
caches that lookup for 15 minutes, invalidates it when the cookie file changes,
and reports failed authentication without guessing. Messages without an author
ID are shown with both boxes checked but omitted by a single-group filter.
Choices persist in YTL preferences and shareable URLs. Capture-presence facets,
video-detail chat search, and channel Chat history retain their existing scope.

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
