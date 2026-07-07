1|"""FastAPI + SSE server for micron agent."""
2|import asyncio
3|import json
4|import os
5|import mimetypes
6|import uuid
7|from contextlib import asynccontextmanager
8|from datetime import datetime
9|from pathlib import Path
10|from typing import AsyncGenerator
11|
12|from fastapi import FastAPI, File, Request, UploadFile
13|from fastapi.middleware.cors import CORSMiddleware
14|from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
15|from fastapi.staticfiles import StaticFiles
16|from pydantic import BaseModel
17|
18|from micron.agent import create_agent, AgentConfig, MicronAgent
19|from micron.llm import create_backend
20|
21|# App state
22|agent: MicronAgent | None = None
23|
24|
25|@asynccontextmanager
26|async def lifespan(app: FastAPI):
27|    """Initialize agent on startup if not already set (e.g. via run_server)."""
28|    global agent
29|
30|    # Skip if agent was already injected by run_server()
31|    if agent is not None:
32|        print(f"[micron] Using provided agent (LLM: {'available' if agent.llm and agent.llm.is_available() else 'N/A'})")
33|        yield
34|        return
35|    
36|    # Get config from environment variables
37|    provider = os.getenv("MICRON_PROVIDER", "llamacpp")
38|    model = os.getenv("MICRON_MODEL", "models/smollm2-1.7b-q4_k_m.gguf")
39|    context_dir = os.getenv("MICRON_CONTEXT_DIR", "context")
40|    temperature = float(os.getenv("MICRON_TEMPERATURE", "0.1"))
41|    max_tokens = int(os.getenv("MICRON_MAX_TOKENS", "2048"))
42|    n_threads = int(os.getenv("MICRON_THREADS", "8"))
43|    n_gpu_layers = int(os.getenv("MICRON_GPU_LAYERS", "0"))
44|    
45|    # Create agent
46|    agent = create_agent(
47|        context_dir=context_dir,
48|        temperature=temperature,
49|        max_tokens=max_tokens,
50|    )
51|    
52|    # Create and attach LLM backend
53|    try:
54|        backend = create_backend(
55|            provider=provider,
56|            model=model,
57|            n_threads=n_threads,
58|            n_gpu_layers=n_gpu_layers,
59|        )
60|        agent.llm = backend
61|        print(f"[micron] Loaded {provider} backend with model: {model}")
62|    except Exception as e:
63|        print(f"[micron] Warning: Could not load LLM backend: {e}")
64|        print("[micron] Server will run without LLM (tools/memory only)")
65|    
66|    yield
67|    # Cleanup on shutdown
68|
69|
70|app = FastAPI(
71|    title="micron",
72|    description="Lightweight AI agent API",
73|    version="0.1.0",
74|    lifespan=lifespan,
75|)
76|
77|# CORS for local development
78|app.add_middleware(
79|    CORSMiddleware,
80|    allow_origins=["*"],
81|    allow_credentials=True,
82|    allow_methods=["*"],
83|    allow_headers=["*"],
84|)
85|
86|STATIC_DIR = Path(__file__).parent / "static"
87|app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
88|
89|
90|class ChatRequest(BaseModel):
91|    message: str
92|    history: list[dict] | None = None
93|    stream: bool = True
94|    confirm: bool = False
95|    pending_writes: list[dict] | None = None
96|
97|
98|class MemoryRequest(BaseModel):
99|    text: str
100|    tags: list[str] | None = None
101|    importance: int = 3
102|
103|
104|class SearchRequest(BaseModel):
105|    query: str
106|    k: int = 5
107|    tags: list[str] | None = None
108|
109|
110|async def generate_sse(message, history, confirm=False, pending_writes=None):
111|    """Generate SSE events from agent response."""
112|    from micron.agent import ToolCall
113|    try:
114|        calls = None
115|        if confirm and pending_writes:
116|            calls = [ToolCall(
117|                name=w["tool_name"], args=w.get("args", {}),
118|                call_id=w.get("call_id", f"confirm_{i}"), is_write=True,
119|            ) for i, w in enumerate(pending_writes)]
120|        for chunk in agent.run(message, history=history, confirm=confirm, pending_tool_calls=calls):
121|            yield f"data: {json.dumps(chunk)}\n\n"
122|            await asyncio.sleep(0)
123|    except Exception as e:
124|        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
125|    finally:
126|        yield "data: [DONE]\n\n"
127|
128|
129|@app.post("/chat")
130|async def chat(request: ChatRequest):
131|    """Chat with the agent. Returns SSE stream or JSON response."""
132|    if agent.llm is None:
133|        return {"error": "LLM backend not configured", "response": "Server is running without LLM. Configure via MICRON_PROVIDER and MICRON_MODEL env vars."}
134|    
135|    if request.stream:
136|        return StreamingResponse(
137|            generate_sse(request.message, request.history, confirm=request.confirm, pending_writes=request.pending_writes),
138|            media_type="text/event-stream",
139|        )
140|    else:
141|        # Non-streaming: collect full response
142|        try:
143|            response_text = ""
144|            events = []
145|            for chunk in agent.run(request.message, history=request.history, confirm=request.confirm, pending_tool_calls=request.pending_writes):
146|                if chunk["type"] == "text":
147|                    response_text += chunk["content"]
148|                events.append(chunk)
149|            return {"response": response_text, "events": events}
150|        except Exception as e:
151|            return {"error": str(e), "response": ""}
152|
153|
154|@app.get("/health")
155|async def health():
156|    """Health check endpoint."""
157|    return {
158|        "status": "ok",
159|        "tools": len(agent.tools.list()) if agent else 0,
160|        "memories": len(agent.memory) if agent else 0,
161|        "llm_configured": agent.llm is not None if agent else False,
162|    }
163|
164|
165|@app.get("/tools")
166|async def list_tools():
167|    """List available tools."""
168|    return {"tools": agent.tools.list() if agent else []}
169|
170|
171|@app.post("/memory")
172|async def add_memory(request: MemoryRequest):
173|    """Add a memory entry."""
174|    mid = agent.add_memory(request.text, tags=request.tags, importance=request.importance)
175|    return {"id": mid}
176|
177|
178|@app.get("/memory")
179|async def list_memories(n: int = 20):
180|    """List recent memories."""
181|    memories = agent.list_memories(n) if agent else []
182|    return {"memories": [{"id": m.id, "text": m.text, "tags": m.tags, "importance": m.importance} for m in memories]}
183|
184|
185|@app.post("/memory/search")
186|async def search_memory(request: SearchRequest):
187|    """Search memories."""
188|    results = agent.search_memory(request.query, k=request.k, tags=request.tags) if agent else []
189|    return {"results": [{"id": r.id, "text": r.text, "tags": r.tags, "score": 0} for r in results]}
190|
191|
192|@app.delete("/memory/{memory_id}")
193|async def delete_memory(memory_id: str):
194|    """Delete a memory entry."""
195|    success = agent.memory.delete(memory_id) if agent else False
196|    return {"success": success}
197|
198|
199|@app.post("/skills/reload")
200|async def reload_skills():
201|    """Reload skills from disk."""
202|    if agent:
203|        agent.reload_skills()
204|    return {"tools": agent.tools.list() if agent else []}
205|
206|
207|# ── Web UI ──────────────────────────────────────────────────────────────
208|
209|
210|@app.get("/", response_class=HTMLResponse)
async def web_ui():
    return FileResponse(str(STATIC_DIR / "index.html"))


414|
415|
416|@app.get("/", response_class=HTMLResponse)
417|async def web_ui():
418|    return HTML_PAGE
419|
420|
421|@app.post("/upload")
422|async def upload_file(file: UploadFile = File(...)):
423|    """Upload a file to context/uploads/ and return its path."""
424|    upload_dir = Path(agent.context_dir) / "uploads" if agent else Path("context/uploads")
425|    upload_dir.mkdir(parents=True, exist_ok=True)
426|
427|    # Sanitize filename — keep extension but replace other unsafe chars
428|    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in file.filename or "file")
429|    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
430|    unique_name = f"{ts}_{safe_name}"
431|    dest = upload_dir / unique_name
432|
433|    content = await file.read()
434|    if len(content) > 10 * 1024 * 1024:  # 10MB limit
435|        return {"error": "File too large (max 10MB)"}
436|
437|    dest.write_bytes(content)
438|
439|    return {
440|        "path": str(dest),
441|        "filename": safe_name,
442|        "size": len(content),
443|        "mimetype": file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
444|    }
445|
446|
447|def run_server(agent_instance, host: str = "[IP_ADDRESS]", port: int = 8000):
448|    """Run the FastAPI server with the given agent instance."""
449|    global agent
450|    agent = agent_instance
451|    import uvicorn
452|    print(f"[micron] Web UI at http://{host}:{port}")
453|    uvicorn.run(app, host=host, port=port)
454|
455|
456|def main():
457|    """Run the server."""
458|    import uvicorn
459|    host = os.getenv("MICRON_HOST", "0.0.0.0")
460|    port = int(os.getenv("MICRON_PORT", "8000"))
461|    uvicorn.run(app, host=host, port=port)
462|
463|
464|if __name__ == "__main__":
465|    main()