# Carry-On

**Take your AI memory with you.** Switch between ChatGPT, Claude and Gemini subscriptions
without losing years of conversations: Carry-On imports the official data exports of all three
into one searchable archive on your own hardware, and serves it over
[MCP](https://modelcontextprotocol.io) so whichever assistant you use today can search what you
discussed with the others.

Runs as a Home Assistant add-on (aarch64 / amd64), with optional built-in Tailscale Funnel so
claude.ai and chatgpt.com can reach it without a domain or port forwarding.

[中文说明](README.zh-CN.md)

## Features
- **Official exports only** — no browser extension, no scraping, no session cookies.
  Drop the export zip into a folder; re-export any time, imports are incremental.
- **Faithful parsing** — keeps only the branch you actually ended on (edits/regenerations
  dropped), voice-chat transcripts, attachment text, Gemini Canvas code; merges Gemini Takeout
  across exports since Google deletes activity after 18 months.
- **CJK-friendly search** — SQLite FTS5 with a trigram tokenizer: Chinese/Japanese work without
  word segmentation.
- **Works with web connectors** — streamable HTTP; tools follow the ChatGPT connector
  `search`/`fetch` convention and also work in Claude custom connectors and any MCP client.
- **Small** — ~1400 ChatGPT + ~900 Gemini conversations ≈ 130 MB database, ~220 MB RAM.

## Install
[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fshenyinzhe%2Fcarryon)

Or add `https://github.com/shenyinzhe/carryon` as a repository in the add-on store, then
install **Carry-On**. The first install builds the image on your device (a few minutes).
See [carryon/DOCS.md](carryon/DOCS.md) for configuration, importing and connecting.

## Tools
| Tool | |
|---|---|
| `search(query, source?)` | Keyword search across all conversations (any language) |
| `fetch(id)` | Full text of one conversation |
| `list_recent(limit?, source?)` | Most recently updated conversations |
| `archive_stats()` | Number of conversations per source |

## Security
Authentication is a long random **secret path** (`https://<host>/<secret>/mcp`), because
Claude custom connectors accept only authless or OAuth servers. Treat the whole URL like a
password; the server never logs request paths. OAuth is on the roadmap.

## Running without Home Assistant
```bash
cd carryon
pip install -r requirements.txt
python -m carryon.cli --db carryon.db import chatgpt-export.zip claude-export.zip takeout.zip
python -m carryon.cli --db carryon.db search "vector database"
CARRYON_DATA=. CARRYON_INBOX=./inbox CARRYON_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(32))") \
  python -m carryon.server
```

## Roadmap
- Prebuilt multi-arch images
- Hybrid vector search with a multilingual embedding model
- OAuth instead of the secret path
- `save_note` tool so assistants can write conclusions back

## License
[MIT](LICENSE)
