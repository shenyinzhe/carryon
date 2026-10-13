"""End-to-end over streamable HTTP: secret path and the MCP tools."""
import importlib
import json
import os
import sys

import pytest
from starlette.testclient import TestClient

from exports import write_chatgpt, write_gemini

SECRET = "s" * 40
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    os.environ.update(CARRYON_DATA=str(data), CARRYON_SECRET=SECRET)
    sys.modules.pop("carryon.server", None)
    srv = importlib.import_module("carryon.server")
    for p in (write_chatgpt(data), write_gemini(data)):
        srv.import_path(p)
    with TestClient(srv.mcp.streamable_http_app()) as client:
        yield client


def rpc(client, method, params, path=SECRET):
    return client.post(f"/{path}/mcp", headers=HEADERS,
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def test_wrong_path_is_404(server):
    assert rpc(server, "tools/list", {}, path="guess").status_code == 404
    assert server.post("/mcp", headers=HEADERS, json={}).status_code == 404


def test_initialize_and_list_tools(server):
    r = rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "carry-on"
    tools = {t["name"] for t in rpc(server, "tools/list", {}).json()["result"]["tools"]}
    assert tools == {"search", "fetch", "list_recent", "archive_stats"}


def call(server, name, **args):
    r = rpc(server, "tools/call", {"name": name, "arguments": args}).json()["result"]
    return json.loads(r["content"][0]["text"])


def test_search_then_fetch(server):
    [hit] = call(server, "search", query="向量数据库")["results"]
    assert hit["id"] == "chatgpt:gpt-1" and hit["url"] == "https://chatgpt.com/c/gpt-1"
    doc = call(server, "fetch", id=hit["id"])
    assert "4 GB 足够。" in doc["text"] and doc["metadata"]["source"] == "chatgpt"
    assert call(server, "archive_stats") == {"chatgpt": 1, "gemini": 2}
