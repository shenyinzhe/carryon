# Carry-On — project context

Take your AI memory with you when switching assistants/subscriptions: imports official
ChatGPT / Claude / Gemini chat exports into one searchable archive, served over MCP
(streamable HTTP) so Claude and ChatGPT custom connectors (or any MCP client) can search it.
Packaged as a Home Assistant add-on. MIT licensed, public repo github.com/shenyinzhe/carryon.
Docs: README.md (English), README.zh-CN.md (Chinese), carryon/DOCS.md (shown in HA UI).
Personal deployment notes live in CLAUDE.local.md (gitignored) — never commit them.

## Layout
- `repository.yaml` — makes the repo an HA add-on repository; `carryon/` is the add-on
  (build context: `config.yaml`, `Dockerfile`, `run.sh`, `translations/`, Python package).
- `carryon/run.sh` — optional built-in **Tailscale Funnel**: userspace tailscaled, state in
  /data/tailscale, `tailscale funnel --bg 8765`; tailscaled output → /dev/null so the secret
  path never hits logs. Chosen over Cloudflare Tunnel (needs a domain) and over the community
  Tailscale add-on (its Funnel only exposes HA itself).
- `carryon/carryon/importers.py` — streams exports with ijson; detects format by content, not filename.
  - ChatGPT: `mapping` tree; follow `current_node` back to root to drop regenerated branches;
    skip system/tool messages, `recipient != "all"`, hidden messages, thoughts/reasoning_recap.
    2026 export shards into conversations-000..NNN.json (each a top-level array; handled as-is).
    Voice chats: text is in `parts[]` dicts with content_type audio_transcription. Assistant text
    has private-use UI markup `kind[args]` (+ // spans):
    keep entity display names / url labels / product names, drop cite/genui/map/etc.
  - Claude (2026 export = manifest + per-category zips; only conversations-000.zip matters):
    `chat_messages` holds all edit/retry branches flattened → follow newest leaf via
    `parent_message_uuid`. Use `content[type=text]`, not `text` (contains "This block is not
    supported…" placeholders for tool calls). Append `attachments[].extracted_content` and
    `files[].file_name`. Some exported convs are fully blank (no name/content) → skipped.
  - Gemini: Takeout "My Activity" JSON. Group by thread id from `details[].url`
    (`gemini.google.com/app/<hex>`); entries without one (canvas creation) join the thread
    active in the last 30 min, else `s<ts>` sessions. Canvas code is in `subtitles`;
    attachments listed in `subtitles` with `url`. db.upsert merges (keeps older stored
    messages) because Takeout auto-deletes activity after 18 months.
- `carryon/carryon/db.py` — SQLite. Chunks = user turn + following assistant turns, split into
  2000-char windows (200 overlap) so long pastes are fully indexed. FTS5 with
  **trigram tokenizer** (CJK without word splitting); terms <3 chars fall back to LIKE.
  Upsert dedups by `source:orig_id` + updated_at/message count.
- `carryon/carryon/server.py` — FastMCP (**mcp SDK pinned <2**; 2.x renamed FastMCP → MCPServer).
  Tools: search, fetch, list_recent, archive_stats. `search`/`fetch` follow the ChatGPT
  connector convention ({results:[{id,title,url,text}]}). Inbox watcher imports zips from
  `/share/carryon/inbox` every 5 min and moves them to `/share/carryon/imported`.
  Secret read from `$CARRYON_SECRET` or `/data/options.json`.
- `carryon/carryon/cli.py` — `cd carryon && python -m carryon.cli --db x.db import|search|fetch|stats`.
- `deploy.sh` — dev loop: tar `carryon/` over `ssh $CARRYON_SSH_HOST` to /addons/carryon, then
  `ha apps install|update|rebuild local_carryon`. Strips `image:` from config.yaml so the local
  copy builds from source instead of pulling the release.
- Same image runs standalone (`compose.yaml`): add-on options ↔ env `CARRYON_<OPTION>` (env wins,
  read in run.sh / server.py). Dockerfile arch: `BUILD_ARCH` (HA builder) or `TARGETARCH` (docker).
- `tests/` — pytest on synthetic exports of all three formats + MCP over HTTP (`pytest` from root).
- `.github/workflows/ci.yml` — tests, then native amd64/arm64 image build + container smoke test
  (200 on secret path, 404 elsewhere, secret not in log). Tag `vX.Y.Z` (= config.yaml version)
  pushes ghcr `{amd64,aarch64}-carryon:X.Y.Z` (HA) and multi-arch `carryon:X.Y.Z/latest` (Docker).
  config.yaml has `image:`, so HA pulls instead of building. Release = bump version, push main,
  tag right away: HA offers the update as soon as main changes, and pulls fail until CI (~5 min)
  has pushed that version.

## Security decisions
- Auth = long random **secret path** (`/<secret>/mcp`). Reason: Claude custom connectors
  accept only authless or OAuth (user-pasted bearer tokens not supported). The whole URL is a
  credential. uvicorn access log is disabled so the secret never lands in HA logs — keep it so.
- Container only maps `share:rw`; keep it isolated from HA config.
- Never commit exports, databases, tailnet names or secrets (see .gitignore).

## Status
- Verified on real exports: Gemini Takeout (3151 entries → 891 threads), Claude (52 convs),
  ChatGPT (1403 convs, 11093 msgs). Combined db ~131 MB, ~216 MB RAM on an aarch64 box.
- Claude connector verified against a public Funnel URL.
- v0.3.0: renamed Chat History Hub → Carry-On, restructured as an add-on repository.
- v0.4.0: standalone Docker (env config), CI + ghcr images, synthetic-export tests.

## Next steps (in order)
1. Vector search: multilingual model (bge-m3 or multilingual-e5-small; NOT all-MiniLM — poor
   on Chinese). Build embeddings on a PC, ship the db; box only embeds queries (int8 ONNX).
   sqlite-vec for storage; hybrid rank with FTS (e.g. RRF).
2. OAuth (DCR) to replace the secret path.
3. `save_note` tool for writing conclusions back (portable memory, not just history).

## Prior art checked (none fits)
MyChatArchive (no Gemini, English-only embeddings, AGPL), kept (browser-extension capture,
desktop app), chat-history-index-mcp (only ChatGPT native), gpt-history-mcp (macOS,
undocumented API). No HA add-on does this. HACS does not distribute add-ons.
