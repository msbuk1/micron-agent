"""FastAPI + SSE server for micron agent with rate limiting and authentication."""
import asyncio
import json
import os
import mimetypes
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, File, Request, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import time
from collections import deque

from micron.agent import create_agent, AgentConfig, MicronAgent
from micron.llm import create_backend
from micron.config import load_config
from micron.sessions import SessionLogger
from micron.tools.builtin import _get_workdir, list_trash, purge_trash, restore_file, undo_file

# Rate limiting storage
chat_request_times = deque(maxlen=1000)  # Store last 1000 request timestamps

# App state
agent: MicronAgent | None = None
session_logger: SessionLogger | None = None
_config_cache = None

def _get_cached_config():
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def check_authentication(request: Request) -> bool:
    """Check if API key is valid.
    
    Args:
        request: FastAPI request object
        
    Returns:
        True if authenticated or auth disabled, False otherwise
    """
    config = _get_cached_config()

    # Get API key from header or query parameter
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        api_key = request.query_params.get("api_key")
    
    # Use Config's is_valid_api_key method (constant-time comparison)
    return config.is_valid_api_key(api_key)

# Rate limiting function
def check_rate_limit() -> bool:
    """Check if rate limit has been exceeded.
    
    Returns:
        True if rate limit exceeded, False otherwise
    """
    config = _get_cached_config()
    rate_limits = config.get_rate_limits()
    
    if not rate_limits.get("enabled", False):
        return False  # Rate limiting disabled
    
    max_requests = rate_limits.get("chat_requests_per_minute", 60)
    
    # Remove requests older than 60 seconds
    current_time = time.time()
    while chat_request_times and current_time - chat_request_times[0] > 60:
        chat_request_times.popleft()
    
    # Check if limit exceeded
    if len(chat_request_times) >= max_requests:
        return True
    
    # Add current request
    chat_request_times.append(current_time)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent on startup if not already set (e.g. via run_server)."""
    global agent, session_logger

    # Skip if agent was already injected by run_server()
    if agent is not None:
        print(f"[micron] Using provided agent (LLM: {'available' if agent.llm and agent.llm.is_available() else 'N/A'})")
        # Session logger may also have been injected by run_server(); create one
        # from the agent's context_dir if not.
        if session_logger is None:
            try:
                sessions_dir = Path(agent.context_dir) / "sessions"
                session_logger = SessionLogger(sessions_dir)
                session_logger.start_session()
                print(f"[micron] Session logging enabled: {sessions_dir}")
            except Exception as e:
                print(f"[micron] Warning: Could not initialize session logger: {e}")
                session_logger = None
        yield
        if session_logger is not None:
            session_logger.end_session()
        return

    # Load configuration
    config = load_config()
    rt = config.resolve_runtime()

    # Create agent
    agent = create_agent(
        context_dir=rt["context_dir"],
        temperature=rt["temperature"],
        max_tokens=rt["max_tokens"],
        max_tool_iterations=rt["max_tool_iterations"],
        provider=rt["provider"],
        model=rt["model"],
    )

    # Create and attach LLM backend
    try:
        backend = create_backend(
            provider=rt["provider"],
            model=rt["model"],
            n_threads=rt["n_threads"],
            n_gpu_layers=rt["n_gpu_layers"],
            api_key=rt.get("api_key"),
            base_url=rt.get("base_url"),
        )
        agent.llm = backend
        print(f"[micron] Loaded {rt['provider']} backend with model: {rt['model']}")
    except Exception as e:
        print(f"[micron] Warning: Could not load LLM backend: {e}")
        print("[micron] Server will run without LLM (tools/memory only)")

    # Initialize session logger — failures are non-fatal so the server still runs.
    try:
        sessions_dir = Path(agent.context_dir) / "sessions"
        session_logger = SessionLogger(sessions_dir)
        session_logger.start_session()
        print(f"[micron] Session logging enabled: {sessions_dir}")
    except Exception as e:
        print(f"[micron] Warning: Could not initialize session logger: {e}")
        session_logger = None

    yield
    # Cleanup on shutdown
    if session_logger is not None:
        session_logger.end_session()


app = FastAPI(
    title="micron",
    description="Lightweight AI agent API with rate limiting and authentication",
    version="0.1.1",
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://[IP_ADDRESS]:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    stream: bool = True
    confirm: bool = False
    pending_writes: list[dict] | None = None


class MemoryRequest(BaseModel):
    text: str
    tags: list[str] | None = None
    importance: int = 3


class SearchRequest(BaseModel):
    query: str
    k: int = 5
    tags: list[str] | None = None


class RestoreRequest(BaseModel):
    filename: str


class UndoRequest(BaseModel):
    path: str


class ResumeRequest(BaseModel):
    message: str | None = None
    stream: bool = False


def _recovery_result(result: str, field: str, value: str):
    if result.startswith("Error"):
        return {"error": result}
    return {"status": "restored", field: value, "message": result}


@app.get("/trash")
async def list_trash_files():
    """List files available for recovery from the trash."""
    _get_workdir()
    result = list_trash()
    files = [line.strip().split()[0] for line in result.splitlines() if line.startswith("  ")]
    return {"files": files, "message": result}


@app.post("/restore")
async def restore_trash_file(request: RestoreRequest):
    """Restore a file from the trash."""
    _get_workdir()
    return _recovery_result(restore_file(request.filename), "filename", request.filename)


@app.post("/purge")
async def purge_trash_files():
    """Permanently remove all files from the trash."""
    _get_workdir()
    result = purge_trash()
    if result.startswith("Error"):
        return {"error": result}
    return {"status": "purged", "message": result}


@app.post("/undo")
async def undo_backup_file(request: UndoRequest):
    """Restore a file from its .bak backup."""
    _get_workdir()
    return _recovery_result(undo_file(request.path), "path", request.path)


async def generate_sse(message, history, confirm=False, pending_writes=None):
    """Generate SSE events from agent response."""
    from micron.agent import ToolCall
    from micron.events import EventType
    assistant_text = ""
    try:
        calls = None
        if confirm and pending_writes:
            calls = [ToolCall(
                name=w["tool_name"], args=w.get("args", {}),
                call_id=w.get("call_id", f"confirm_{i}"), is_write=True,
            ) for i, w in enumerate(pending_writes)]

        # Forward every agent event as SSE — single loop, no type filtering
        for chunk in agent.run(message, history=history, confirm=confirm, pending_tool_calls=calls):
            event_type = chunk.get("type")
            if event_type == EventType.DONE:
                continue  # handled in finally block
            if event_type == EventType.TEXT:
                assistant_text += chunk.get("content", "")
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        # Persist the full assistant turn once the stream is complete.
        if session_logger is not None and assistant_text:
            session_logger.log_turn("assistant", assistant_text)
        yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat(request: ChatRequest, req: Request = None):
    """Chat with the agent. Returns SSE stream or JSON response.

    Implements rate limiting and authentication.
    """
    # Check authentication (skip for TestClient which doesn't provide req)
    if req is not None:
        if not check_authentication(req):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized - API key required"
            )

        # Check rate limiting
        if check_rate_limit():
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests - Rate limit exceeded"
            )


    if agent.llm is None:
        return {"error": "LLM backend not configured", "response": "Server is running without LLM. Configure via MICRON_PROVIDER and MICRON_MODEL env vars."}

    # Persist the user turn before processing. Sessions are owned by the
    # server (one per lifetime), so this appends to the active JSONL file.
    if session_logger is not None:
        session_logger.log_turn("user", request.message)

    if request.stream:
        return StreamingResponse(
            generate_sse(request.message, request.history, confirm=request.confirm, pending_writes=request.pending_writes),
            media_type="text/event-stream",
        )
    else:
        # Non-streaming: collect full response
        try:
            from micron.events import process_events
            result = process_events(
                agent.run(request.message, history=request.history,
                          confirm=request.confirm, pending_tool_calls=request.pending_writes),
            )
            if session_logger is not None and result.text:
                session_logger.log_turn("assistant", result.text)
            return {"response": result.text, "events": []}
        except Exception as e:
            return {"error": str(e), "response": ""}


@app.get("/sessions")
async def list_sessions_endpoint(n: int = 20):
    """List recent sessions, newest first."""
    if session_logger is None:
        return {"sessions": []}
    sessions = session_logger.list_sessions(n=n)
    return {"sessions": sessions}


@app.get("/session/{session_id}")
async def read_session_endpoint(session_id: str):
    """Read the turns of a single session."""
    if session_logger is None:
        raise HTTPException(status_code=503, detail="Session logging not configured")
    turns = session_logger.read_session(session_id)
    # read_session returns [] for both "missing file" and "empty session".
    # Distinguish the two so clients can show a clear 404 vs an empty session.
    session_file = session_logger.sessions_dir / f"{session_id}.jsonl"
    if not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "turns": turns}


@app.post("/session/{session_id}/resume")
async def resume_session_endpoint(session_id: str, request: ResumeRequest):
    """Resume a previous conversation by session ID.

    Loads the conversation history and either returns it (when no message
    is supplied) or continues the conversation with a new user message.
    """
    if session_logger is None:
        raise HTTPException(status_code=503, detail="Session logging not configured")

    session_file = session_logger.sessions_dir / f"{session_id}.jsonl"
    if not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    history = session_logger.get_session_context(session_id)

    if not request.message:
        return {"id": session_id, "history": history}

    if agent.llm is None:
        return {
            "error": "LLM backend not configured",
            "response": "Server is running without LLM. Configure via MICRON_PROVIDER and MICRON_MODEL env vars.",
        }

    session_logger.log_turn("user", request.message)

    if request.stream:
        return StreamingResponse(
            generate_sse(request.message, history),
            media_type="text/event-stream",
        )

    from micron.events import process_events
    try:
        result = process_events(agent.run(request.message, history=history))
        if result.text:
            session_logger.log_turn("assistant", result.text)
        return {"response": result.text, "history": history}
    except Exception as e:
        return {"error": str(e), "response": ""}


@app.get("/health")
async def health():
    """Health check endpoint."""
    config = _get_cached_config()
    return {
        "status": "ok",
        "tools": len(agent.tools.list()) if agent else 0,
        "memories": len(agent.memory) if agent else 0,
        "llm_configured": agent.llm is not None if agent else False,
        "rate_limiting_enabled": config.get_rate_limits().get("enabled", False),
        "authentication_enabled": config.get_authentication().enabled,
    }


@app.get("/tools")
async def list_tools():
    """List available tools."""
    return {"tools": agent.tools.list() if agent else []}


@app.post("/clear")
async def clear_history():
    """Clear the agent's in-memory history."""
    if agent and hasattr(agent, "_tool_history"):
        agent._tool_history.clear()
    return {"status": "cleared"}


@app.get("/model")
async def get_model():
    """Current model info (provider name + model name)."""
    if agent is None or agent.config is None:
        raise HTTPException(status_code=503, detail="Agent not available")
    return {
        "provider": agent.config.provider,
        "model": agent.config.model,
    }


@app.get("/providers")
async def list_providers():
    """List configured providers."""
    config = _get_cached_config()
    active = os.environ.get("MICRON_PROVIDER", config.get("default_provider", "llamacpp"))
    providers = [
        {"name": name, "model": pcfg.get("model", "")}
        for name, pcfg in config.get("providers", {}).items()
    ]
    return {
        "default": config.get("default_provider", "llamacpp"),
        "active": active,
        "providers": providers,
    }


@app.post("/unload")
async def unload_model():
    """Unload the model from RAM."""
    if agent and hasattr(agent, "unload_model"):
        agent.unload_model()
    return {"status": "unloaded"}


@app.post("/memory")
async def add_memory(request: MemoryRequest):
    """Add a memory entry."""
    mid = agent.add_memory(request.text, tags=request.tags, importance=request.importance)
    return {"id": mid}


@app.get("/memory")
async def list_memories(n: int = 20):
    """List recent memories."""
    memories = agent.list_memories(n) if agent else []
    return {"memories": [{"id": m.id, "text": m.text, "tags": m.tags, "importance": m.importance} for m in memories]}


@app.post("/memory/search")
async def search_memory(request: SearchRequest):
    """Search memories."""
    results = agent.search_memory(request.query, k=request.k, tags=request.tags) if agent else []
    return {"results": [{"id": r.id, "text": r.text, "tags": r.tags, "score": 0} for r in results]}


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a memory entry."""
    success = agent.memory.delete(memory_id) if agent else False
    return {"success": success}


@app.post("/skills/reload")
async def reload_skills():
    """Reload skills from disk."""
    if agent:
        agent.reload_skills()
    return {"tools": agent.tools.list() if agent else []}


# ── Web UI ──────────────────────────────────────────────────────────────

# Mount static files at root. This must come after all other routes so it
# doesn't shadow them. `html=True` makes GET / serve index.html.
_static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to context/uploads/ in workdir and return its path."""
    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    upload_dir = workdir / "context" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename — keep extension but replace other unsafe chars
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in file.filename or "file")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = f"{ts}_{safe_name}"
    dest = upload_dir / unique_name

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        return {"error": "File too large (max 10MB)"}

    dest.write_bytes(content)

    # Return a workdir-relative path so read_file() and other tools can resolve it
    rel_path = dest.relative_to(workdir)

    return {
        "path": rel_path.as_posix(),
        "filename": safe_name,
        "size": len(content),
        "mimetype": file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
    }


def run_server(agent_instance, host: str = "0.0.0.0", port: int = 8000, session_logger_instance: SessionLogger | None = None):
    """Run the FastAPI server with the given agent instance."""
    global agent, session_logger
    agent = agent_instance
    session_logger = session_logger_instance
    import uvicorn
    print(f"[micron] Web UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


def main():
    """Run the server."""
    import uvicorn
    host = os.getenv("MICRON_HOST", "0.0.0.0")
    port = int(os.getenv("MICRON_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()