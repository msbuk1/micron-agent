"""Integration tests for the FastAPI server endpoints.

Uses httpx.AsyncClient with ASGITransport for async testing.
"""
import json
import os
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, ASGITransport

os.environ["MICRON_WORKDIR"] = str(Path(__file__).parent.parent)
os.environ["MICRON_CONTEXT_DIR"] = str(Path(__file__).parent.parent / "context")

import micron.server as srv
from micron.server import app
from micron.agent import create_agent
from micron.llm import create_backend
from micron.sessions import SessionLogger


@pytest.fixture(scope="module")
async def client():
    """Create an AsyncClient for testing, with a real agent, bypassing lifespan."""
    context_dir = Path(__file__).parent.parent / "context"
    (context_dir / "memory").mkdir(exist_ok=True)
    (context_dir / "sessions").mkdir(exist_ok=True)

    backend = create_backend(
        provider="lmstudio",
        model="minicpm5-1b",
        api_key="no_key",
        base_url="http://localhost:1234/v1",
    )

    srv.agent = create_agent(
        context_dir=str(context_dir),
        provider="lmstudio",
        model="minicpm5-1b",
        temperature=0.1,
        max_tokens=2048,
        llm_kwargs={"backend": backend},
    )

    # Override lifespan to no-op so it doesn't create a new agent
    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app.router.lifespan_context = noop_lifespan

    ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield ac
    await ac.aclose()


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["tools"] > 0

    async def test_health_llm_configured(self, client):
        resp = await client.get("/health")
        assert resp.json()["llm_configured"] is True


class TestToolsEndpoint:
    async def test_list_tools(self, client):
        resp = await client.get("/tools")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        names = [t["name"] for t in tools]
        assert "web_search" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "run_command" in names
        assert "search_knowledge" in names

    async def test_tools_have_required_fields(self, client):
        resp = await client.get("/tools")
        tools = resp.json()["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool


class TestMemoryEndpoints:
    async def test_add_memory(self, client):
        resp = await client.post("/memory", json={"text": "test memory", "tags": ["test"], "importance": 3})
        assert resp.status_code == 200
        assert "id" in resp.json()

    async def test_list_memories(self, client):
        resp = await client.get("/memory?n=5")
        assert resp.status_code == 200
        assert isinstance(resp.json()["memories"], list)

    async def test_search_memory(self, client):
        resp = await client.post("/memory/search", json={"query": "test", "k": 5})
        assert resp.status_code == 200
        assert "results" in resp.json()


class TestChatEndpoint:
    async def test_chat_no_llm(self, client):
        original = srv.agent.llm
        srv.agent.llm = None
        resp = await client.post("/chat", json={"message": "hello"})
        srv.agent.llm = original
        assert "error" in resp.json()

    async def test_chat_non_streaming(self, client):
        resp = await client.post("/chat", json={"message": "What is 2+2?", "stream": False})
        assert resp.status_code == 200
        data = resp.json()
        # LLM might fail to load — that's OK, we're testing endpoint plumbing
        assert "response" in data or "error" in data

    async def test_chat_streaming(self, client):
        resp = await client.post(
            "/chat",
            json={"message": "What is 2+2?", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
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
    async def test_reload_skills(self, client):
        resp = await client.post("/skills/reload")
        assert resp.status_code == 200
        assert len(resp.json()["tools"]) > 0


class TestSessionLogging:
    """Chat exchanges should append to a JSONL session file matching the CLI format."""

    async def test_chat_writes_user_and_assistant_turns(self, client, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        session_id = logger.start_session()

        original_logger = srv.session_logger
        original_run = srv.agent.run
        srv.session_logger = logger
        # Stub agent.run so we don't need a working LLM.
        def fake_run(message, history=None, confirm=False, pending_tool_calls=None, **_):
            yield {"type": "text", "content": "stubbed-reply"}
            yield {"type": "done"}
        monkeypatch.setattr(srv.agent, "run", fake_run)

        try:
            resp = await client.post(
                "/chat",
                json={"message": "hello server", "stream": False},
            )
            assert resp.status_code == 200
        finally:
            srv.session_logger = original_logger
            srv.agent.run = original_run
            logger.end_session()

        session_file = sessions_dir / f"{session_id}.jsonl"
        assert session_file.exists()
        lines = [json.loads(line) for line in session_file.read_text().splitlines()]
        # First line is the CLI-style header.
        assert lines[0]["type"] == "session_start"
        assert lines[0]["id"] == session_id
        # User turn was logged before processing.
        user_turn = next(e for e in lines if e["type"] == "turn" and e["role"] == "user")
        assert user_turn["content"] == "hello server"
        # Assistant turn was logged after the run completed.
        assistant_turns = [e for e in lines if e["type"] == "turn" and e["role"] == "assistant"]
        assert any(e["content"] == "stubbed-reply" for e in assistant_turns)
        # session_end marker is the final line.
        assert lines[-1]["type"] == "session_end"

    async def test_chat_logging_is_optional(self, client, tmp_path):
        """Server should still respond when no session logger is wired up."""
        original = srv.session_logger
        srv.session_logger = None
        try:
            resp = await client.post(
                "/chat",
                json={"message": "hello", "stream": False},
            )
            assert resp.status_code == 200
        finally:
            srv.session_logger = original


class TestSessionEndpoints:
    """Listing, reading, and resuming conversations by session ID."""

    async def test_list_sessions(self, client, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        session_id = logger.start_session()
        logger.log_turn("user", "first message")
        logger.log_turn("assistant", "first reply")
        logger.end_session()

        original_logger = srv.session_logger
        srv.session_logger = logger
        try:
            resp = await client.get("/sessions")
            assert resp.status_code == 200
            sessions = resp.json()["sessions"]
            ids = [s["id"] for s in sessions]
            assert session_id in ids
        finally:
            srv.session_logger = original_logger

    async def test_read_session(self, client, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        session_id = logger.start_session()
        logger.log_turn("user", "hello")
        logger.log_turn("assistant", "world")
        logger.end_session()

        original_logger = srv.session_logger
        srv.session_logger = logger
        try:
            resp = await client.get(f"/session/{session_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == session_id
            turns = data["turns"]
            assert len(turns) == 2
            assert turns[0]["role"] == "user"
            assert turns[0]["content"] == "hello"
            assert turns[1]["role"] == "assistant"
            assert turns[1]["content"] == "world"
        finally:
            srv.session_logger = original_logger

    async def test_read_session_not_found(self, client, tmp_path):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        original_logger = srv.session_logger
        srv.session_logger = logger
        try:
            resp = await client.get("/session/does_not_exist")
            assert resp.status_code == 404
        finally:
            srv.session_logger = original_logger

    async def test_resume_session(self, client, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        session_id = logger.start_session()
        logger.log_turn("user", "earlier question")
        logger.log_turn("assistant", "earlier answer")

        original_logger = srv.session_logger
        original_run = srv.agent.run

        def fake_run(message, history=None, confirm=False, pending_tool_calls=None, **_):
            yield {"type": "text", "content": "follow-up-reply"}
            yield {"type": "done"}

        srv.session_logger = logger
        monkeypatch.setattr(srv.agent, "run", fake_run)
        try:
            resp = await client.post(
                f"/session/{session_id}/resume",
                json={"message": "follow-up question", "stream": False},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["response"] == "follow-up-reply"
            # Loaded history from disk should be returned alongside the reply.
            history = data["history"]
            assert history[0] == {"role": "user", "content": "earlier question"}
            assert history[1] == {"role": "assistant", "content": "earlier answer"}
        finally:
            srv.session_logger = original_logger
            srv.agent.run = original_run
            logger.end_session()

    async def test_resume_returns_history_only(self, client, tmp_path):
        """Calling /resume with no message just returns the loaded history."""
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        session_id = logger.start_session()
        logger.log_turn("user", "hi")
        logger.log_turn("assistant", "hello!")

        original_logger = srv.session_logger
        srv.session_logger = logger
        try:
            resp = await client.post(f"/session/{session_id}/resume", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == session_id
            assert data["history"][0] == {"role": "user", "content": "hi"}
            assert data["history"][1] == {"role": "assistant", "content": "hello!"}
        finally:
            srv.session_logger = original_logger
            logger.end_session()

    async def test_resume_nonexistent_session(self, client, tmp_path):
        sessions_dir = tmp_path / "sessions"
        logger = SessionLogger(sessions_dir)
        original_logger = srv.session_logger
        srv.session_logger = logger
        try:
            resp = await client.post(
                "/session/does_not_exist/resume",
                json={"message": "hi", "stream": False},
            )
            assert resp.status_code == 404
        finally:
            srv.session_logger = original_logger


class TestWebUI:
    """Static UI served from micron/static/ — verifies the seam, not the markup."""

    async def test_get_root_serves_index_html(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.text
        assert "<title>micron</title>" in body
        assert "/style.css" in body
        assert "/app.js" in body

    async def test_get_style_css(self, client):
        resp = await client.get("/style.css")
        assert resp.status_code == 200
        assert ":root" in resp.text
        assert "--bg" in resp.text

    async def test_get_app_js_has_event_renderer(self, client):
        resp = await client.get("/app.js")
        assert resp.status_code == 200
        body = resp.text
        assert "class EventRenderer" in body
        for method in ("text", "thinking", "tool_start", "tool_result",
                       "tool_error", "confirmation_required", "error", "done"):
            assert method in body, f"EventRenderer missing {method} handler"

    async def test_index_has_no_inline_styles_or_scripts(self, client):
        """Static seam — index.html is markup only, no inline CSS/JS."""
        resp = await client.get("/")
        assert "<style" not in resp.text
        import re
        # Allow external script references like `<script src="..."></script>`,
        # but no inline `<script>...</script>` blocks.
        inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", resp.text)
        assert inline_scripts == [], f"Inline scripts found: {inline_scripts}"
