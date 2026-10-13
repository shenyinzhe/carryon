"""Parse ChatGPT / Claude / Gemini exports into one normalized structure.

Input can be a .zip export, an extracted folder, or a single .json file.
Formats are detected by content, not file name (Takeout folder names are localized).
Large files are streamed with ijson, so a multi-hundred-MB conversations.json
does not have to fit in RAM as Python objects.
"""
from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, IO, Iterator

import ijson

log = logging.getLogger(__name__)

GEMINI_GAP_SECONDS = 30 * 60  # Takeout has no thread ids: split sessions on 30-min gaps


@dataclass
class Message:
    role: str  # "user" | "assistant"
    text: str
    ts: float | None = None


@dataclass
class Conversation:
    source: str  # "chatgpt" | "claude" | "gemini"
    orig_id: str
    title: str
    created_at: float | None
    updated_at: float | None
    messages: list[Message] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.orig_id}"


# ---------------------------------------------------------------- helpers

def _iso(s) -> float | None:
    if not s:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class _HTMLText(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.cells = 0  # cells seen in the current table row

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        elif tag == "tr":
            self.cells = 0
            if self.parts and not self.parts[-1].endswith("\n"):
                self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | " if self.cells else "| ")
            self.cells += 1
        elif tag == "pre":
            self.parts.append("\n```\n")
        elif tag == "hr":
            self.parts.append("\n---\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")
        elif tag == "tr":
            self.parts.append(" |\n" if self.cells else "\n")
        elif tag == "pre":
            self.parts.append("```\n" if self.parts and self.parts[-1].endswith("\n") else "\n```\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- ChatGPT

_CHATGPT_SKIP_TYPES = {"user_editable_context", "thoughts", "reasoning_recap"}


# Inline UI markup in assistant text: \ue200<kind>[\ue202<args...>]\ue201, plus span markers
# \ue203..\ue204 and \ue206. Keep what the user saw as text, drop citations and widgets.
_CHATGPT_MARKUP = re.compile("\ue200(\\w+)(?:\ue202(.*?))?\ue201", re.S)  # args optional: \ue200map\ue201
_CHATGPT_SPAN = re.compile("[\ue200-\ue206]")  # span markers + unpaired leftovers
# Uploaded photos are usually named by UUID / "image.png": not worth indexing.
_GENERIC_FILE = re.compile(r"^([0-9A-Fa-f-]{36}|image|IMG_\d+|file-\w+)\.\w+$")


def _chatgpt_markup(m: re.Match) -> str:
    kind, args = m.group(1), m.group(2) or ""
    try:
        if kind == "entity":  # ["brand", "ASUS", 0] -> ASUS
            return str(json.loads(args)[1])
        if kind == "url":  # label \ue202 url
            return args.split("\ue202")[0]
        if kind == "products":
            return "[" + ", ".join(s[1] for s in json.loads(args)["selections"]) + "]"
    except (ValueError, LookupError, TypeError):
        pass
    return ""  # cite / filecite / memcite / genui / image_group / ...


def _chatgpt_text(content: dict) -> str:
    if content.get("content_type") in _CHATGPT_SKIP_TYPES:
        return ""
    if isinstance(content.get("parts"), list):
        parts = [p if isinstance(p, str) else p.get("text") or "" for p in content["parts"]
                 if isinstance(p, str) or (isinstance(p, dict)
                                           and p.get("content_type") == "audio_transcription")]
        text = "\n".join(p for p in parts if p)
    elif isinstance(content.get("text"), str):
        text = content["text"]
    else:
        return ""
    return _CHATGPT_SPAN.sub("", _CHATGPT_MARKUP.sub(_chatgpt_markup, text))


def parse_chatgpt(item: dict) -> Conversation | None:
    oid = item.get("conversation_id") or item.get("id")
    mapping = item.get("mapping") or {}
    if not oid or not mapping:
        return None

    # Follow the branch the user last saw (edits/regenerations create a tree).
    node_id = item.get("current_node")
    if node_id not in mapping:
        leaves = [n for n in mapping.values() if not n.get("children")]
        leaves.sort(key=lambda n: ((n.get("message") or {}).get("create_time") or 0))
        node_id = leaves[-1]["id"] if leaves else None

    chain, seen = [], set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        chain.append(mapping[node_id])
        node_id = mapping[node_id].get("parent")
    chain.reverse()

    msgs = []
    for node in chain:
        m = node.get("message")
        if not m:
            continue
        role = (m.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue  # system / tool output
        if m.get("recipient", "all") != "all":
            continue  # assistant -> tool calls
        if (m.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
            continue
        text = _chatgpt_text(m.get("content") or {})
        files = [a["name"] for a in (m.get("metadata") or {}).get("attachments") or []
                 if a.get("name") and not _GENERIC_FILE.match(a["name"])]
        if files:
            text += "\n[附件: " + ", ".join(files) + "]"
        if text.strip():
            msgs.append(Message(role, text, m.get("create_time")))

    return Conversation("chatgpt", str(oid), item.get("title") or "",
                        _iso(item.get("create_time")), _iso(item.get("update_time")), msgs)


# ---------------------------------------------------------------- Claude

def _claude_branch(messages: list[dict]) -> list[dict]:
    """chat_messages holds every edit/retry branch flattened; keep the newest leaf's chain."""
    by_id = {m.get("uuid"): m for m in messages}
    if len(by_id) != len(messages) or not all(m.get("parent_message_uuid") for m in messages):
        return messages  # older exports: linear, no tree info
    parents = {m["parent_message_uuid"] for m in messages}
    leaves = [m for m in messages if m["uuid"] not in parents]
    if not leaves:
        return messages
    node = max(leaves, key=lambda m: m.get("created_at") or "")
    chain, seen = [], set()
    while node and node["uuid"] not in seen:
        seen.add(node["uuid"])
        chain.append(node)
        node = by_id.get(node["parent_message_uuid"])
    return chain[::-1]


def _claude_text(m: dict) -> str:
    # Prefer content blocks: `text` also holds "This block is not supported..." placeholders
    # for tool calls. thinking / tool_use / tool_result / injected prompts are skipped.
    blocks = [b.get("text", "") for b in m.get("content") or []
              if isinstance(b, dict) and b.get("type") == "text"]
    text = "\n\n".join(b for b in blocks if b.strip()) or m.get("text") or ""
    done = set()
    for a in m.get("attachments") or []:  # pasted text / uploaded docs, extracted by Claude
        if a.get("extracted_content"):
            text += f"\n\n[附件: {a.get('file_name') or '粘贴文本'}]\n{a['extracted_content']}"
            done.add(a.get("file_name"))
    files = [f["file_name"] for f in m.get("files") or [] if f.get("file_name") and f["file_name"] not in done]
    if files:
        text += "\n[附件: " + ", ".join(files) + "]"
    return text.strip()


def parse_claude(item: dict) -> Conversation | None:
    oid = item.get("uuid")
    if not oid:
        return None
    msgs = []
    for m in _claude_branch(item.get("chat_messages") or []):
        role = {"human": "user", "assistant": "assistant"}.get(m.get("sender"))
        if not role:
            continue
        text = _claude_text(m)
        if text:
            msgs.append(Message(role, text, _iso(m.get("created_at"))))
    return Conversation("claude", str(oid), item.get("name") or "",
                        _iso(item.get("created_at")), _iso(item.get("updated_at")), msgs)


# ---------------------------------------------------------------- Gemini (Takeout "My Activity")

_GEMINI_PROMPT_PREFIX = re.compile(r"^(Prompted|Eingegebener Prompt:?|已输入提示:?)\s*", re.I)
_GEMINI_CANVAS_PREFIX = re.compile(r"^Created Gemini Canvas titled\s*", re.I)
_GEMINI_THREAD = re.compile(r"gemini\.google\.com/app/([0-9a-f]+)")

# (ts, thread id or None, prompt, response)
GeminiEntry = tuple[float, "str | None", str, str]


def _gemini_entry(item: dict) -> GeminiEntry | None:
    ts = _iso(item.get("time"))
    if ts is None:
        return None
    title = item.get("title") or ""
    subs = [s for s in item.get("subtitles") or [] if isinstance(s, dict)]
    thread = next((m.group(1) for d in item.get("details") or [] if isinstance(d, dict)
                   if (m := _GEMINI_THREAD.search(d.get("url") or ""))), None)

    if _GEMINI_CANVAS_PREFIX.match(title):  # canvas code only lives in subtitles
        name = _GEMINI_CANVAS_PREFIX.sub("", title, count=1).strip()
        code = "\n".join(s.get("name", "") for s in subs).strip()
        return (ts, thread, "", f"[Canvas{': ' + name if name else ''}]\n{code}") if code else None

    prompt = _GEMINI_PROMPT_PREFIX.sub("", title, count=1).strip()
    files = [s["name"].lstrip("- ").strip() for s in subs if s.get("url") and s.get("name")]
    if files:
        prompt += "\n[附件: " + ", ".join(files) + "]"
    response = "\n\n".join(html_to_text(h.get("html", "")) for h in (item.get("safeHtmlItem") or [])
                           if isinstance(h, dict)).strip()
    is_prompt = bool(_GEMINI_PROMPT_PREFIX.match(title))
    if not response and not is_prompt:
        return None  # feedback, "Selected preferred draft", settings changes, etc.
    return ts, thread, prompt, response


def group_gemini(entries: list[GeminiEntry]) -> Iterator[Conversation]:
    """Group by thread id (gemini.google.com/app/<id>). Entries without one (canvas
    creation, old exports) join the thread active within the last 30 min, else are
    split into sessions on 30-min gaps."""
    entries.sort(key=lambda e: e[0])  # Takeout is newest-first
    groups: dict[str, list[GeminiEntry]] = {}
    last_ts, last_key = None, None
    for e in entries:
        ts, thread = e[0], e[1]
        if thread:
            key = thread
        elif last_key and ts - last_ts <= GEMINI_GAP_SECONDS:
            key = last_key
        else:
            key = f"s{int(ts)}"  # hex thread ids never start with "s"
        groups.setdefault(key, []).append(e)
        last_ts, last_key = ts, key

    for key, group in groups.items():
        msgs = []
        for ts, _, prompt, response in group:
            if prompt:
                msgs.append(Message("user", prompt, ts))
            if response:
                msgs.append(Message("assistant", response, ts))
        first = group[0]
        title = (first[2] or first[3])[:60].replace("\n", " ")
        yield Conversation("gemini", key, title, first[0], group[-1][0], msgs)


def source_url(conv_id: str) -> str:
    """Link back to the original chat where the id allows it."""
    source, _, oid = conv_id.partition(":")
    if source == "chatgpt":
        return f"https://chatgpt.com/c/{oid}"
    if source == "claude":
        return f"https://claude.ai/chat/{oid}"
    if source == "gemini" and not oid.startswith("s"):  # "s<ts>" = time-split session
        return f"https://gemini.google.com/app/{oid}"
    return f"carryon://{conv_id}"


# ---------------------------------------------------------------- source discovery

Opener = Callable[[], IO[bytes]]


def _json_sources(path: Path) -> Iterator[tuple[str, Opener]]:
    if path.is_dir():
        for p in sorted(path.rglob("*.json")):
            yield str(p), (lambda p=p: open(p, "rb"))
    elif zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        for info in zf.infolist():
            if not info.is_dir() and info.filename.lower().endswith(".json"):
                yield f"{path.name}:{info.filename}", (lambda i=info: zf.open(i))
    elif path.suffix.lower() == ".json":
        yield str(path), (lambda: open(path, "rb"))


def _peek_first(opener: Opener):
    try:
        with opener() as f:
            for item in ijson.items(f, "item", use_float=True):
                return item
    except Exception:  # not JSON / not a top-level array
        return None
    return None


def classify(item) -> str | None:
    if not isinstance(item, dict):
        return None
    if "mapping" in item:
        return "chatgpt"
    if "chat_messages" in item:
        return "claude"
    if "time" in item and "header" in item:
        hay = (str(item.get("header")) + " " + " ".join(map(str, item.get("products") or []))).lower()
        if "gemini" in hay or "bard" in hay:
            return "gemini"
    return None


def iter_conversations(path: str | Path) -> Iterator[Conversation]:
    gemini: list[GeminiEntry] = []
    for name, opener in _json_sources(Path(path)):
        kind = classify(_peek_first(opener))
        if not kind:
            continue
        log.info("%s -> %s", name, kind)
        with opener() as f:
            for item in ijson.items(f, "item", use_float=True):
                if kind == "gemini":
                    e = _gemini_entry(item)
                    if e:
                        gemini.append(e)
                    continue
                c = parse_chatgpt(item) if kind == "chatgpt" else parse_claude(item)
                if c and c.messages:
                    yield c
    if gemini:
        yield from group_gemini(gemini)
