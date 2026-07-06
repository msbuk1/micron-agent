"""Integration tests for the FastAPI server endpoints."""
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

os.environ["MICRON_WORKDIR"] = str(Path(__file__).parent.parent)
os.environ["MICRON_CONTEXT_DIR"] = str(Path(__file__).parent.parent / "context")

from fastapi.testclient import TestClient
import micron.server as srv
from micron.server import app
from micron.agent import create_agent
from micron.llm import create_backend


@pytest.fixture(scope="module")
def client():
    """Create a test client with a real agent, bypassing lifespan."""
    context_dir = Path(__file__).parent.parent / "context"
    (context_dir / "memory").mkdir(exist_ok=True)
    (context_dir / "sessions").mkdir(exist_ok=True)

    backend = create_backend(
        provider="lmstudio",
        model="gemma-4-12b-it-qat",
        api_key="no_key",
        base_url="http://192.168.1.162:1234/v1",
    )

    srv.agent = create_agent(
        context_dir=str(context_dir),
        provider="lmstudio",
        model="gemma-4-12b-it-qat",
        temperature=0.1,
        max_tokens=2048,
        llm_kwargs={"backend": backend},
    )

    # Override lifespan to no-op so it doesn't create a new agent
    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app.router.lifespan_context = noop_lifespan

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["tools"] > 0

    def test_health_llm_configured(self, client):
        resp = client.get("/health")
        assert resp.json()["llm_configured"] is True


class TestToolsEndpoint:
    def test_list_tools(self, client):
        resp = client.get("/tools")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        names = [t["name"] for t in tools]
        assert "web_search" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "run_command" in names
        assert "search_knowledge" in names

    def test_tools_have_required_fields(self, client):
        tools = client.get("/tools").json()["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool


class TestMemoryEndpoints:
    def test_add_memory(self, client):
        resp = client.post("/memory", json={"text": "test memory", "tags": ["test"], "importance": 3})
        assert resp.status_code == 200
        assert "id" in resp.json()

    def test_list_memories(self, client):
        resp = client.get("/memory?n=5")
        assert resp.status_code == 200
        assert isinstance(resp.json()["memories"], list)

    def test_search_memory(self, client):
        resp = client.post("/memory/search", json={"query": "test", "k": 5})
        assert resp.status_code == 200
        assert "results" in resp.json()


class TestChatEndpoint:
    def test_chat_no_llm(self, client):
        original = srv.agent.llm
        srv.agent.llm = None
        resp = client.post("/chat", json={"message": "hello"})
        srv.agent.llm = original
        assert "error" in resp.json()

    def test_chat_non_streaming(self, client):
        resp = client.post("/chat", json={"message": "What is 2+2?", "stream": False})
        assert resp.status_code == 200
        data = resp.json()
        # LLM might fail to load — that's OK, we're testing endpoint plumbing
        assert "response" in data or "error" in data

    def test_chat_streaming(self, client):
        resp = client.post("/chat", json={"message": "What is 2+2?", "stream": True},
                           headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        assert len(events) > 0


class TestSkillsEndpoint:
    def test_reload_skills(self, client):
        resp = client.post("/skills/reload")
        assert resp.status_code == 200
        assert len(resp.json()["tools"]) > 0
