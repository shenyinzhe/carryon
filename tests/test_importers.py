from carryon import db
from carryon.importers import iter_conversations

from exports import (T0, gemini_activity, gemini_entry, write_chatgpt, write_claude,
                     write_gemini)


def msgs(conv):
    return [(m.role, m.text) for m in conv.messages]


def test_chatgpt_follows_current_branch(tmp_path):
    [c] = iter_conversations(write_chatgpt(tmp_path))
    assert (c.id, c.title) == ("chatgpt:gpt-1", "向量数据库")
    assert msgs(c) == [
        ("user", "如何搭建向量数据库？\n[附件: plan.pdf]"),  # generic image.png dropped
        ("assistant", "推荐Qdrant或 sqlite-vec。"),        # entity kept, citation dropped
        ("user", "语音提问：内存够吗"),                     # voice transcript
        ("assistant", "4 GB 足够。"),                      # thoughts / tool call / system skipped
    ]


def test_claude_newest_branch_and_attachments(tmp_path):
    convs = list(iter_conversations(write_claude(tmp_path)))
    assert [c.id for c in convs] == ["claude:claude-1"]  # blank conversation skipped
    assert msgs(convs[0]) == [
        ("user", "解释一下 trigram"),
        ("assistant", "三字切分。"),  # retry branch dropped, no tool placeholder
        ("user", "看附件\n\n[附件: notes.txt]\n附件里的长文本\n[附件: diagram.png]"),
    ]


def test_gemini_threads_canvas_and_sessions(tmp_path):
    convs = {c.orig_id: c for c in iter_conversations(write_gemini(tmp_path))}
    assert set(convs) == {"abc123", f"s{T0 + 7200}"}
    thread = convs["abc123"]
    assert msgs(thread) == [
        ("user", "今天天气怎么样"),
        ("assistant", "晴天，25°C"),
        ("user", "看看这个报告\n[附件: 报告.pdf]"),
        ("assistant", "- 要点一\n\n- 要点二"),
        ("assistant", "[Canvas: 天气小程序]\nprint('sunny')"),
    ]
    assert msgs(convs[f"s{T0 + 7200}"]) == [("user", "另一个话题"), ("assistant", "另一个回答")]


def _import(con, path):
    counts = {"new": 0, "updated": 0, "skipped": 0}
    for c in iter_conversations(path):
        counts[db.upsert(con, c)] += 1
    con.commit()
    return counts


def test_reimport_is_incremental(tmp_path):
    con = db.connect(tmp_path / "x.db")
    paths = [write_chatgpt(tmp_path), write_claude(tmp_path), write_gemini(tmp_path)]
    assert [_import(con, p)["new"] for p in paths] == [1, 1, 2]
    assert all(_import(con, p)["skipped"] == n for p, n in zip(paths, [1, 1, 2]))
    assert db.stats(con) == {"chatgpt": 1, "claude": 1, "gemini": 2}


def test_gemini_reimport_keeps_expired_messages(tmp_path):
    con = db.connect(tmp_path / "x.db")
    _import(con, write_gemini(tmp_path))
    # A later Takeout: the thread's first prompt has expired, a new one was added.
    later = [e for e in gemini_activity() if "天气怎么样" not in e["title"]]
    later.insert(0, gemini_entry(T0 + 600, "Prompted 明天呢", "<p>多云</p>", thread="abc123"))
    (tmp_path / "takeout.zip").unlink()
    assert _import(con, write_gemini(tmp_path, later))["updated"] == 1
    texts = [m["text"] for m in con.execute(
        "SELECT text FROM messages WHERE conv_id='gemini:abc123' ORDER BY idx")]
    assert texts[0] == "今天天气怎么样" and texts[-1] == "多云"
    assert con.execute("SELECT title FROM conversations WHERE id='gemini:abc123'").fetchone()[0] \
        == "今天天气怎么样"


def test_search_cjk_short_terms_and_long_pastes(tmp_path):
    con = db.connect(tmp_path / "x.db")
    for p in (write_chatgpt(tmp_path), write_claude(tmp_path), write_gemini(tmp_path)):
        _import(con, p)
    assert [h["id"] for h in db.search(con, "向量数据库")] == ["chatgpt:gpt-1"]  # trigram, no spaces
    assert [h["id"] for h in db.search(con, "晴天")] == ["gemini:abc123"]       # <3 chars: LIKE
    assert [h["id"] for h in db.search(con, "trigram", source="claude")] == ["claude:claude-1"]
    assert db.search(con, "trigram", source="gemini") == []

    from carryon.importers import Conversation, Message
    long = "填充" * 3000 + "藏在末尾的关键词"
    db.upsert(con, Conversation("claude", "long", "长粘贴", T0, T0, [Message("user", long)]))
    assert [h["id"] for h in db.search(con, "藏在末尾的关键词")] == ["claude:long"]
