# YT Live Chat

YT Live Chat is an optional sidecar plugin for YT Library. The informal project
name is **YTLC**.

This initial scaffold establishes the plugin boundary, plugin-owned config and
SQLite database, and zero-state statistics for YT Library's Advanced Plugins
panel. It intentionally does not download chat yet: acquisition depends on a
future YT Library host capability that provides authenticated YouTube access
without moving cookies or proxy configuration into the plugin.

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

On first start, YTLC creates its config and database. YT Library owns the
enable/disable control. When enabled, the Advanced Plugins panel shows the
plugin status and basic capture statistics.

See [docs/design.md](docs/design.md) for the agreed host boundary and future
worker shape.
