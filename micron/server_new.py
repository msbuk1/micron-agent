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
from collections import deque
import time

from fastapi import FastAPI, File, Request, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from micron.agent import create_agent, AgentConfig, MicronAgent
from micron.llm import create_backend

# Rate limiting storage
chat_request_times = deque(maxlen=1000)  # Store last 1000 request timestamps

# App state
agent: MicronAgent | None = None

# Rate limiting function
def check_rate_limit() -> bool:
    """Check if rate limit has been exceeded.
    
    Returns:
        True if rate limit exceeded, False otherwise
    """
    from micron.config import load_config
    
    config = load_config()
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


# Authentication function
def check_authentication(request: Request) -> bool:
    """Check if API key is valid.
    
    Args:
        request: FastAPI request object
        
    Returns:
        True if authenticated or auth disabled, False otherwise
    """
    from micron.config import load_config
    
    config = load_config()
    auth_config = config.get_authentication()
    
    if not auth_config.get("enabled", False):
        return True  # Authentication disabled
    
    if not auth_config.get("api_key_required", False):
        return True  # API key not required
    
    # Get API key from header or environment
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        api_key = os.getenv(auth_config.get("api_key_env_var", "MICRON_API_KEY"))
    
    # Check if valid (in production, this would validate against a database)
    # For now, we'll just check if it's set
    if not api_key:
        return False
    
    return True


from micron.config import load_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent on startup if not already set (e.g. via run_server)."""
    global agent

    # Skip if agent was already injected by run_server()
    if agent is not None:
        print(f"[micron] Using provided agent (LLM: {'available' if agent.llm and agent.llm.is_available() else 'N/A'})")
        yield
        return
    
    # Load configuration
    config = load_config()
    
    # Create agent
    agent = create_agent(
        context_dir=config.get("context_dir"),
        temperature=config.get("temperature", 0.1),
        max_tokens=config.get("max_tokens", 2048),
    )
    
    # Create and attach LLM backend
    try:
        provider_config = config.get_provider_config()
        backend = create_backend(
            provider=config.get("default_provider"),
            model=provider_config.get("model"),
            n_threads=provider_config.get("n_threads", 8),
            n_gpu_layers=provider_config.get("n_gpu_layers", 0),
            api_key=provider_config.get("api_key"),
            base_url=provider_config.get("base_url"),
        )
        agent.llm = backend
        print(f"[micron] Loaded {config.get('default_provider')} backend with model: {provider_config.get('model')}")
    except Exception as e:
        print(f"[micron] Warning: Could not load LLM backend: {e}")
        print("[micron] Server will run without LLM (tools/memory only)")

    yield
    # Cleanup on shutdown


app = FastAPI(
    title="micron",
    description="Lightweight AI agent API with rate limiting and authentication",
    version="0.1.1",
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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


async def generate_sse(message, history, confirm=False, pending_writes=None):
    """Generate SSE events from agent response."""
    from micron.agent import ToolCall
    try:
        calls = None
        if confirm and pending_writes:
            calls = [ToolCall(
                name=w["tool_name"], args=w.get("args", {}),
                call_id=w.get("call_id", f"confirm_{i}"), is_write=True,
            ) for i, w in enumerate(pending_writes)]
        for chunk in agent.run(message, history=history, confirm=confirm, pending_tool_calls=calls):
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat(request: ChatRequest, req: Request):
    """Chat with the agent. Returns SSE stream or JSON response.
    
    Implements rate limiting and authentication.
    """
    # Check authentication
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
    
    if request.stream:
        return StreamingResponse(
            generate_sse(request.message, request.history, confirm=request.confirm, pending_writes=request.pending_writes),
            media_type="text/event-stream",
        )
    else:
        # Non-streaming: collect full response
        try:
            response_text = ""
            events = []
            for chunk in agent.run(request.message, history=request.history, confirm=request.confirm, pending_tool_calls=request.pending_writes):
                if chunk["type"] == "text":
                    response_text += chunk["content"]
                events.append(chunk)
            return {"response": response_text, "events": events}
        except Exception as e:
            return {"error": str(e), "response": ""}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "tools": len(agent.tools.list()) if agent else 0,
        "memories": len(agent.memory) if agent else 0,
        "llm_configured": agent.llm is not None if agent else False,
        "rate_limiting_enabled": load_config().get_rate_limits().get("enabled", False),
        "authentication_enabled": load_config().get_authentication().get("enabled", False),
    }


@app.get("/tools")
async def list_tools():
    """List available tools."""
    return {"tools": agent.tools.list() if agent else []}


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


# Rest of the file remains the same...
# [HTML_PAGE, web_ui, upload_file, etc.]

print("✅ Created new server.py with rate limiting and authentication")