"""Synthetic exports that mimic the real ChatGPT / Claude / Gemini formats (no personal data)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

T0 = 1760000000  # 2025-10-09


def _gpt_node(nid, parent, children, role=None, content=None, **msg):
    message = None
    if role:
        message = {"author": {"role": role}, "content": content, "create_time": T0 + len(nid),
                   "recipient": "all", "metadata": {}, **msg}
    return {"id": nid, "parent": parent, "children": children, "message": message}


def _text(s):
    return {"content_type": "text", "parts": [s]}


def chatgpt_conversation() -> dict:
    mapping = [
        _gpt_node("root", None, ["sys"]),
        _gpt_node("sys", "root", ["u1"], "system", _text("You are ChatGPT")),
        _gpt_node("u1", "sys", ["a1-old", "a1"], "user", _text("如何搭建向量数据库？"),
                  metadata={"attachments": [{"name": "plan.pdf"}, {"name": "image.png"}]}),
        _gpt_node("a1-old", "u1", [], "assistant", _text("被重新生成掉的旧回答")),
        _gpt_node("a1", "u1", ["tool"], "assistant", _text(
            "推荐entity[\"brand\",\"Qdrant\",0]或 sqlite-vec"
            "citeturn0search1。")),
        _gpt_node("tool", "a1", ["u2"], "assistant", _text("search('x')"), recipient="web"),
        _gpt_node("u2", "tool", ["think"], "user", {"content_type": "multimodal_text", "parts": [
            {"content_type": "audio_transcription", "text": "语音提问：内存够吗"},
            {"content_type": "audio_asset_pointer", "asset_pointer": "sediment://x"}]}),
        _gpt_node("think", "u2", ["a2"], "assistant", {"content_type": "thoughts", "thoughts": []}),
        _gpt_node("a2", "think", [], "assistant", _text("4 GB 足够。")),
    ]
    return {"conversation_id": "gpt-1", "title": "向量数据库", "create_time": T0,
            "update_time": T0 + 100, "current_node": "a2", "mapping": {n["id"]: n for n in mapping}}


def write_chatgpt(dir: Path) -> Path:
    path = dir / "chatgpt.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("conversations.json", json.dumps([chatgpt_conversation()]))
    return path


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def claude_conversations() -> list[dict]:
    root = "00000000-0000-4000-8000-000000000000"
    msgs = [
        {"uuid": "m1", "parent_message_uuid": root, "sender": "human", "created_at": _iso(T0),
         "text": "解释一下 trigram", "content": [{"type": "text", "text": "解释一下 trigram"}]},
        {"uuid": "m2-old", "parent_message_uuid": "m1", "sender": "assistant", "created_at": _iso(T0 + 1),
         "text": "旧的重试回答", "content": [{"type": "text", "text": "旧的重试回答"}]},
        {"uuid": "m2", "parent_message_uuid": "m1", "sender": "assistant", "created_at": _iso(T0 + 2),
         "text": "三字切分。\nThis block is not supported on your current device yet.",
         "content": [{"type": "text", "text": "三字切分。"}, {"type": "tool_use", "name": "web_search"}]},
        {"uuid": "m3", "parent_message_uuid": "m2", "sender": "human", "created_at": _iso(T0 + 3),
         "text": "看附件", "content": [{"type": "text", "text": "看附件"}],
         "attachments": [{"file_name": "notes.txt", "extracted_content": "附件里的长文本"}],
         "files": [{"file_name": "notes.txt"}, {"file_name": "diagram.png"}]},
    ]
    return [
        {"uuid": "claude-1", "name": "Trigram", "created_at": _iso(T0), "updated_at": _iso(T0 + 3),
         "chat_messages": msgs},
        {"uuid": "claude-blank", "name": "", "created_at": _iso(T0), "updated_at": _iso(T0),
         "chat_messages": []},
    ]


def write_claude(dir: Path) -> Path:
    # 2026 exports ship per-category zips; conversations-000.zip holds conversations.json.
    path = dir / "conversations-000.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(claude_conversations()))
    return path


def gemini_entry(ts, title, html=None, thread=None, subtitles=None):
    e = {"header": "Gemini Apps", "title": title, "time": _iso(ts), "products": ["Gemini Apps"]}
    if html:
        e["safeHtmlItem"] = [{"html": html}]
    if thread:
        e["details"] = [{"name": "From your Gemini Apps Activity",
                         "url": f"https://gemini.google.com/app/{thread}"}]
    if subtitles:
        e["subtitles"] = subtitles
    return e


def gemini_activity() -> list[dict]:
    entries = [
        gemini_entry(T0, "Prompted 今天天气怎么样", "<p>晴天，<b>25°C</b></p>", thread="abc123"),
        gemini_entry(T0 + 120, "Prompted 看看这个报告", "<ul><li>要点一</li><li>要点二</li></ul>",
                     thread="abc123", subtitles=[{"name": "- 报告.pdf", "url": "https://drive.google.com/x"}]),
        # Canvas creation has no thread link: joins the thread active within 30 min.
        gemini_entry(T0 + 300, "Created Gemini Canvas titled 天气小程序",
                     subtitles=[{"name": "print('sunny')"}]),
        gemini_entry(T0 + 400, "Gave feedback: Good response"),
        # Two hours later without a thread link: a separate time-split session.
        gemini_entry(T0 + 7200, "Prompted 另一个话题", "<p>另一个回答</p>"),
    ]
    return entries[::-1]  # Takeout lists newest first


def write_gemini(dir: Path, entries=None) -> Path:
    path = dir / "takeout.zip"
    with zipfile.ZipFile(path, "w") as zf:
        # Folder names are localized; detection must not rely on them.
        zf.writestr("Takeout/Meine Aktivitäten/Gemini Apps/MeineAktivitäten.json",
                    json.dumps(entries if entries is not None else gemini_activity()))
    return path
