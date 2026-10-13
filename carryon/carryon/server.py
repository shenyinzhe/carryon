"""MCP server (streamable HTTP) exposing the chat archive.

Auth: the endpoint lives under a long random secret path, e.g.
  https://carryon.example.com/<SECRET>/mcp
Claude's custom connectors currently accept authless or OAuth servers only,
so a secret path is the simplest thing both Claude and ChatGPT can use.
Treat the full URL like a password.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import db
from .importers import iter_conversations, source_url

log = logging.getLogger("carryon")

DATA = Path(os.environ.get("CARRYON_DATA", "/data"))
INBOX = Path(os.environ.get("CARRYON_INBOX", "/share/carryon/inbox"))
PORT = int(os.environ.get("CARRYON_PORT", "8765"))
_opts = DATA / "options.json"  # written by Home Assistant from the add-on config
SECRET = os.environ.get("CARRYON_SECRET") or (
    json.loads(_opts.read_text()).get("secret", "") if _opts.exists() else "")

if len(SECRET) < 32:
    raise SystemExit("CARRYON_SECRET must be at least 32 characters")

con = db.connect(DATA / "carryon.db")
lock = threading.Lock()

mcp = FastMCP(
    "carry-on",
    instructions=(
        "Search the user's past conversations with ChatGPT, Claude and Gemini. "
        "Use `search` with a few distinctive keywords (any language; Chinese terms need "
        "no spaces), then `fetch` a result id to read the whole conversation. "
        "Results are the user's own history: cite title and date when using them."
    ),
    host="0.0.0.0",
    port=PORT,
    streamable_http_path=f"/{SECRET}/mcp",
    stateless_http=True,
    json_response=True,
)


# All tools only read the local archive; ChatGPT skips its per-call confirmation for these.
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)


def _date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else None


@mcp.tool(annotations=READ_ONLY)
def search(query: str, source: str | None = None, limit: int = 8) -> str:
    """Keyword search over past chats. source: chatgpt | claude | gemini | None (all).
    Returns JSON {results:[{id,title,url,text}]}; pass an id to fetch."""
    with lock:
        hits = db.search(con, query, limit=min(limit, 20), source=source)
    return json.dumps({"results": [
        {"id": h["id"], "title": f"[{h['source']} {_date(h['updated_at'])}] {h['title']}",
         "url": source_url(h["id"]), "text": h["snippet"]} for h in hits]}, ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def fetch(id: str) -> str:
    """Return the full text of one conversation by id (from search or list_recent)."""
    with lock:
        c = db.fetch(con, id)
    if not c:
        return json.dumps({"error": f"no conversation {id}"})
    return json.dumps({"id": c["id"], "title": c["title"], "url": source_url(c["id"]),
                       "text": c["text"],
                       "metadata": {"source": c["source"], "created": _date(c["created_at"]),
                                    "updated": _date(c["updated_at"])}}, ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def list_recent(limit: int = 20, source: str | None = None) -> str:
    """List the most recently updated conversations."""
    with lock:
        rows = db.recent(con, min(limit, 50), source)
    return json.dumps([{**r, "updated_at": _date(r["updated_at"])} for r in rows], ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY)
def archive_stats() -> str:
    """Number of archived conversations per source."""
    with lock:
        return json.dumps(db.stats(con))


# ---------------------------------------------------------------- inbox watcher

def import_path(path: Path) -> dict:
    counts = {"new": 0, "updated": 0, "skipped": 0}
    with lock:
        for conv in iter_conversations(path):
            counts[db.upsert(con, conv)] += 1
        con.commit()
    return counts


def watch_inbox(interval: int = 300):
    done = INBOX.parent / "imported"
    while True:
        try:
            INBOX.mkdir(parents=True, exist_ok=True)
            done.mkdir(parents=True, exist_ok=True)
            for p in sorted(INBOX.iterdir()):
                if p.suffix.lower() not in (".zip", ".json") or time.time() - p.stat().st_mtime < 30:
                    continue  # still being copied
                log.info("importing %s", p.name)
                try:
                    log.info("%s: %s", p.name, import_path(p))
                    shutil.move(str(p), done / p.name)
                except Exception:
                    log.exception("import failed: %s", p.name)
                    shutil.move(str(p), done / (p.name + ".failed"))
        except Exception:
            log.exception("inbox watcher error")
        time.sleep(interval)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threading.Thread(target=watch_inbox, daemon=True).start()
    log.info("serving on :%d (path /<secret>/mcp), %s", PORT, db.stats(con))
    import uvicorn  # run directly so the access log (which contains the secret path) is off
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=PORT, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
