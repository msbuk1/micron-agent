"""FastAPI + SSE server for micron agent."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from micron.agent import create_agent, AgentConfig, MicronAgent
from micron.llm import create_backend

# App state
agent: MicronAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent on startup."""
    global agent
    
    # Get config from environment variables
    provider = os.getenv("MICRON_PROVIDER", "llamacpp")
    model = os.getenv("MICRON_MODEL", "models/smollm2-1.7b-q4_k_m.gguf")
    context_dir = os.getenv("MICRON_CONTEXT_DIR", "context")
    temperature = float(os.getenv("MICRON_TEMPERATURE", "0.1"))
    max_tokens = int(os.getenv("MICRON_MAX_TOKENS", "2048"))
    n_threads = int(os.getenv("MICRON_THREADS", "8"))
    n_gpu_layers = int(os.getenv("MICRON_GPU_LAYERS", "0"))
    
    # Create agent
    agent = create_agent(
        context_dir=context_dir,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    
    # Create and attach LLM backend
    try:
        backend = create_backend(
            provider=provider,
            model=model,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
        )
        agent.llm = backend
        print(f"[micron] Loaded {provider} backend with model: {model}")
    except Exception as e:
        print(f"[micron] Warning: Could not load LLM backend: {e}")
        print("[micron] Server will run without LLM (tools/memory only)")
    
    yield
    # Cleanup on shutdown


app = FastAPI(
    title="micron",
    description="Lightweight AI agent API",
    version="0.1.0",
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


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    stream: bool = True


class MemoryRequest(BaseModel):
    text: str
    tags: list[str] | None = None
    importance: int = 3


class SearchRequest(BaseModel):
    query: str
    k: int = 5
    tags: list[str] | None = None


async def generate_sse(agent: MicronAgent, message: str, history: list[dict] | None) -> AsyncGenerator[str, None]:
    """Generate SSE events from agent response."""
    try:
        for chunk in agent.run(message, history=history):
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0)  # Yield control
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat(request: ChatRequest):
    """Chat with the agent. Returns SSE stream or JSON response."""
    if agent.llm is None:
        return {"error": "LLM backend not configured", "response": "Server is running without LLM. Configure via MICRON_PROVIDER and MICRON_MODEL env vars."}
    
    if request.stream:
        return StreamingResponse(
            generate_sse(agent, request.message, request.history),
            media_type="text/event-stream",
        )
    else:
        # Non-streaming: collect full response
        try:
            response_text = ""
            events = []
            for chunk in agent.run(request.message, history=request.history):
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


def main():
    """Run the server."""
    import uvicorn
    host = os.getenv("MICRON_HOST", "0.0.0.0")
    port = int(os.getenv("MICRON_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()