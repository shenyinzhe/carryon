"""SQLite storage + FTS5 search.

Uses the trigram tokenizer so Chinese/Japanese (no spaces) are searchable.
Trigram needs >=3 characters per term; shorter queries fall back to LIKE.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from .importers import Conversation, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, source TEXT, title TEXT,
  created_at REAL, updated_at REAL, n_messages INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
  conv_id TEXT, idx INTEGER, role TEXT, text TEXT, ts REAL,
  PRIMARY KEY (conv_id, idx)
);
CREATE TABLE IF NOT EXISTS chunks (
  rowid INTEGER PRIMARY KEY, conv_id TEXT, chunk_idx INTEGER, msg_start INTEGER, text TEXT
);
CREATE INDEX IF NOT EXISTS chunks_conv ON chunks(conv_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, title, content='', tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY, created_at REAL, text TEXT
);
"""

CHUNK_CHARS = 2000    # one user turn + following assistant turn(s) per chunk ...
CHUNK_OVERLAP = 200   # ... split into overlapping windows when longer, so all text is indexed


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def _windows(text: str):
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for i in range(0, max(len(text) - CHUNK_OVERLAP, 1), step):
        yield text[i:i + CHUNK_CHARS]


def _chunks(conv: Conversation):
    """Group messages into user->assistant exchanges, windowed to CHUNK_CHARS."""
    cur, start = [], 0
    for i, m in enumerate(conv.messages):
        if m.role == "user" and cur:
            for w in _windows("\n\n".join(cur)):
                yield start, w
            cur, start = [], i
        prefix = "用户: " if m.role == "user" else "AI: "
        cur.append(prefix + m.text)
    if cur:
        for w in _windows("\n\n".join(cur)):
            yield start, w


def _delete(con: sqlite3.Connection, conv_id: str):
    rows = con.execute("SELECT rowid, text FROM chunks WHERE conv_id=?", (conv_id,)).fetchall()
    title = (con.execute("SELECT title FROM conversations WHERE id=?", (conv_id,)).fetchone() or [""])[0]
    for r in rows:  # contentless FTS needs the original values to delete
        con.execute("INSERT INTO chunks_fts(chunks_fts, rowid, text, title) VALUES('delete', ?, ?, ?)",
                    (r["rowid"], r["text"], title))
    con.execute("DELETE FROM chunks WHERE conv_id=?", (conv_id,))
    con.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


def upsert(con: sqlite3.Connection, conv: Conversation) -> str:
    """Returns 'new', 'updated' or 'skipped'."""
    row = con.execute("SELECT title, updated_at, n_messages FROM conversations WHERE id=?",
                      (conv.id,)).fetchone()
    if row and (row["updated_at"] or 0) >= (conv.updated_at or 0) and row["n_messages"] >= len(conv.messages):
        return "skipped"
    status = "updated" if row else "new"
    if row and conv.source == "gemini":
        # Gemini activity auto-deletes after 18 months by default: a newer Takeout may lack
        # the start of a thread, so keep stored messages older than the export's first one.
        older = [Message(r["role"], r["text"], r["ts"]) for r in con.execute(
            "SELECT role, text, ts FROM messages WHERE conv_id=? AND ts < ? ORDER BY idx",
            (conv.id, conv.created_at or 0))]
        if older:
            conv = replace(conv, title=row["title"], created_at=older[0].ts,
                           messages=older + conv.messages)
    if row:
        _delete(con, conv.id)
    con.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)",
                (conv.id, conv.source, conv.title, conv.created_at, conv.updated_at, len(conv.messages)))
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?)",
                    [(conv.id, i, m.role, m.text, m.ts) for i, m in enumerate(conv.messages)])
    for ci, (start, text) in enumerate(_chunks(conv)):
        cur = con.execute("INSERT INTO chunks(conv_id, chunk_idx, msg_start, text) VALUES (?,?,?,?)",
                          (conv.id, ci, start, text))
        con.execute("INSERT INTO chunks_fts(rowid, text, title) VALUES (?,?,?)",
                    (cur.lastrowid, text, conv.title))
    return status


# ---------------------------------------------------------------- search

def _terms(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", query.strip()) if t]


def _snippet(text: str, terms: list[str], width: int = 300) -> str:
    low = text.lower()
    pos = min((low.find(t.lower()) for t in terms if low.find(t.lower()) >= 0), default=0)
    start = max(0, pos - width // 3)
    s = text[start:start + width].replace("\n", " ")
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")


def search(con: sqlite3.Connection, query: str, limit: int = 10, source: str | None = None) -> list[dict]:
    terms = _terms(query)
    if not terms:
        return []
    src_sql, src_args = ("AND c.source=?", [source]) if source else ("", [])
    if all(len(t) >= 3 for t in terms):
        fts_q = " ".join('"' + t.replace('"', '""') + '"' for t in terms)
        sql = f"""SELECT ch.conv_id, ch.chunk_idx, ch.text, c.title, c.source, c.updated_at,
                         bm25(chunks_fts) AS score
                  FROM chunks_fts JOIN chunks ch ON ch.rowid = chunks_fts.rowid
                  JOIN conversations c ON c.id = ch.conv_id
                  WHERE chunks_fts MATCH ? {src_sql}
                  ORDER BY score LIMIT ?"""
        rows = con.execute(sql, [fts_q, *src_args, limit * 3]).fetchall()
    else:  # short CJK terms like "天气"
        like = " AND ".join("(ch.text LIKE ? OR c.title LIKE ?)" for _ in terms)
        args = [a for t in terms for a in (f"%{t}%", f"%{t}%")]
        sql = f"""SELECT ch.conv_id, ch.chunk_idx, ch.text, c.title, c.source, c.updated_at, 0 AS score
                  FROM chunks ch JOIN conversations c ON c.id = ch.conv_id
                  WHERE {like} {src_sql} ORDER BY c.updated_at DESC LIMIT ?"""
        rows = con.execute(sql, [*args, *src_args, limit * 3]).fetchall()

    out, seen = [], set()
    for r in rows:  # at most one hit per conversation
        if r["conv_id"] in seen:
            continue
        seen.add(r["conv_id"])
        out.append({"id": r["conv_id"], "title": r["title"], "source": r["source"],
                    "updated_at": r["updated_at"], "chunk": r["chunk_idx"],
                    "snippet": _snippet(r["text"], terms)})
        if len(out) >= limit:
            break
    return out


def fetch(con: sqlite3.Connection, conv_id: str, max_chars: int = 40000) -> dict | None:
    c = con.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not c:
        return None
    parts, total = [], 0
    for m in con.execute("SELECT role, text FROM messages WHERE conv_id=? ORDER BY idx", (conv_id,)):
        line = f"[{m['role']}]\n{m['text']}"
        if total + len(line) > max_chars:
            parts.append("…(truncated)")
            break
        parts.append(line)
        total += len(line)
    return {"id": c["id"], "title": c["title"], "source": c["source"],
            "created_at": c["created_at"], "updated_at": c["updated_at"], "text": "\n\n".join(parts)}


def recent(con: sqlite3.Connection, limit: int = 20, source: str | None = None) -> list[dict]:
    q = "SELECT id, title, source, updated_at FROM conversations"
    args: list = []
    if source:
        q += " WHERE source=?"
        args.append(source)
    q += " ORDER BY updated_at DESC LIMIT ?"
    return [dict(r) for r in con.execute(q, [*args, limit])]


def stats(con: sqlite3.Connection) -> dict:
    return {r["source"]: r["n"] for r in
            con.execute("SELECT source, COUNT(*) n FROM conversations GROUP BY source")}
