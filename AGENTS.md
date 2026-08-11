# Repository Guidelines

Read this file at the start of every chat. Treat `TODO.md` as the source for
unfinished or deferred work.

## Working Agreement

- This is the standalone YT Live Chat sidecar for YT Library. Keep its Python
  package, SQLite database, config, tests, and future capture artifacts in this
  repository; do not add plugin-specific storage to YT Library.
- Preserve the optional-plugin boundary. YT Library may load YTLC through its
  versioned plugin API, but YT Library core must not import `yt_live_chat`.
- YT Library owns YouTube authentication, safe cookie handling, proxy settings,
  request policy, and shared queue capacity. Do not add cookie or proxy settings
  to YTLC configuration.
- Keep live capture and replay retrieval as separate queued work. A metadata
  scan may enqueue work, but it must never perform chat acquisition inline.
- Do not infer current broadcast state from `video_type`, and do not infer chat
  availability from broadcast state. Follow the host contract documented in
  `docs/design.md`.
- Prefer Python implementations. Inspect `git status` before editing, preserve
  unrelated changes, run the complete local checks, and commit each coherent,
  verified change unless asked not to. Push only when explicitly requested.
- Runtime SQLite databases, configs, captures, cookies, and logs are private
  local data and must not be committed.

## Verification

Use the YT Library virtual environment from this repository root:

```powershell
$python = "..\YT Library\.venv\Scripts\python.exe"
$files = (Get-ChildItem yt_live_chat,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
& $python -m py_compile @files
& $python -m unittest discover -s tests -v
& $python -m ruff check .
git diff --check
```

Changes affecting plugin registration or status also require live verification
through YT Library's admin status API and Advanced Plugins UI. Use YT Library's
`scripts\service.ps1` for service operations; do not interrupt active workers
solely to reload this plugin.
