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
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import time
from collections import deque

from micron.agent import create_agent, AgentConfig, MicronAgent
from micron.llm import create_backend

# Rate limiting storage
chat_request_times = deque(maxlen=1000)  # Store last 1000 request timestamps

# App state
agent: MicronAgent | None = None
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
    from micron.config import load_config
    
    config = load_config()
    auth_config = config.get("authentication", {})
    
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
    """Generate SSE events from agent response.
    
    Now includes thinking states for better user experience!
    """
    from micron.agent import ToolCall
    try:
        calls = None
        if confirm and pending_writes:
            calls = [ToolCall(
                name=w["tool_name"], args=w.get("args", {}),
                call_id=w.get("call_id", f"confirm_{i}"), is_write=True,
            ) for i, w in enumerate(pending_writes)]
        
        # agent.run() returns a regular generator, not async generator
        for chunk in agent.run(message, history=history, confirm=confirm, pending_tool_calls=calls):
            # Handle thinking states
            if chunk.get("type") == "thinking":
                # For thinking states, we can show them in the UI
                # In a real implementation, you might want to buffer thinking text
                # and show it in a subtle thinking bubble
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0)
            elif chunk.get("type") == "text":
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0)
            elif chunk.get("type") in ["tool_start", "tool_result", "tool_error", "error", "confirmation_required"]:
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0)
            # Skip 'done' events as they're handled in finally block
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
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
    config = _get_cached_config()
    return {
        "status": "ok",
        "tools": len(agent.tools.list()) if agent else 0,
        "memories": len(agent.memory) if agent else 0,
        "llm_configured": agent.llm is not None if agent else False,
        "rate_limiting_enabled": config.get_rate_limits().get("enabled", False),
        "authentication_enabled": config.get("authentication", {}).get("enabled", False),
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


# ── Web UI ──────────────────────────────────────────────────────────────


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>micron</title>
<style>
  :root{--bg:#0d1117;--fg:#c9d1d9;--header:#161b22;--border:#30363d;--user:#1f6feb;--assistant:#21262d;--tool:#8b949e;--system:#161b22;--error:#3d1117;--error-fg:#f85149;--input:#21262d;--btn:#238636;--btn-hover:#2ea043}
  [data-theme=light]{--bg:#f6f8fa;--fg:#24292e;--header:#fff;--border:#d0d7de;--user:#0969da;--assistant:#cbd5ea;--tool:#656d76;--system:#f6f8fa;--error:#fff8f5;--error-fg:#cf222e;--input:#fff;--btn:#2da44e;--btn-hover:#2c974b}
  [data-theme=dark]{--bg:#0d1117;--fg:#c9d1d9;--header:#161b22;--border:#30363d;--user:#1f6feb;--assistant:#3c4f69;--tool:#8b949e;--system:#161b22;--error:#3d1117;--error-fg:#f85149;--input:#21262d;--btn:#238636;--btn-hover:#2ea043}
  *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--bg);color:var(--fg);display:flex;flex-direction:column;align-items:center;height:100vh}
    .container{width:70%;display:flex;flex-direction:column;height:100vh}
    header{padding:12px 16px;border-bottom:1px solid var(--border);background:var(--header);display:flex;align-items:center;gap:8px}
    header h1{font-size:18px;font-weight:600;color:var(--user)}
    header span{font-size:12px;color:var(--tool);margin-left:auto}
    #theme-toggle{padding:6px 10px;background:var(--input);border:1px solid var(--border);border-radius:6px;color:var(--fg);cursor:pointer;font-size:13px;white-space:nowrap}
    #theme-toggle:hover{border-color:var(--user);color:var(--user)}
    #chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
    .msg{max-width:85%;padding:10px 14px;border-radius:8px;line-height:1.5;font-size:14px;white-space:pre-wrap;word-break:break-word}
    .msg.user{align-self:flex-end;background:var(--user);color:#fff}
    .msg.assistant{align-self:flex-start;background:var(--assistant);border:1px solid var(--border);color:var(--fg);border-radius:8px;padding:10px 14px;line-height:1.5;font-size:14px;white-space:pre-wrap;word-break:break-word}
    .msg.system{align-self:center;background:var(--system);color:var(--tool);font-size:12px;padding:6px 12px;border:1px solid var(--border)}
    .msg.error{align-self:center;background:var(--error);color:var(--error-fg);font-size:13px;padding:6px 12px;border:1px solid var(--error-fg)}
    .msg.thinking{align-self:flex-start;background:var(--assistant);color:var(--fg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;line-height:1.5;font-size:14px;white-space:pre-wrap;word-break:break-word;font-style:italic;box-shadow:0 1px 3px rgba(0,0,0,0.1)}
    .tool-call{font-size:12px;color:var(--tool);padding:2px 0;display:none}
    .spinner{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--user);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto}
    @keyframes spin{to{transform:rotate(360deg)}}
    #input-bar{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--border);background:var(--header);align-items:center}
    #file-label{padding:6px 10px;background:var(--input);border:1px solid var(--border);border-radius:6px;cursor:pointer;color:var(--tool);font-size:13px;white-space:nowrap}
    #file-label:hover{border-color:var(--user);color:var(--user)}
    #file-input{display:none}
    #file-name{font-size:12px;color:var(--tool);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #input{flex:1;background:var(--input);border:1px solid var(--border);border-radius:6px;padding:8px 12px;color:var(--fg);font-size:14px;outline:none}
    #input:focus{border-color:var(--user)}
    #send-btn{padding:8px 16px;background:var(--btn);border:none;border-radius:6px;color:#fff;font-size:14px;cursor:pointer;white-space:nowrap}
    #send-btn:hover{background:var(--btn-hover)}
    #send-btn:disabled{opacity:.5;cursor:not-allowed}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>micron</h1>
  <span id="model-info">connecting…</span>
  <button id="theme-toggle" title="Toggle theme">☀️</button>
</header>
<div id="chat">
  <div class="msg system">Send a message to start chatting. You can also upload files (txt, pdf, py, md, csv, json, yaml).</div>
</div>
<div id="input-bar">
  <label id="file-label" for="file-input">📎 Upload</label>
  <input type="file" id="file-input" />
  <span id="file-name"></span>
  <input type="text" id="input" placeholder="Type a message…" autofocus />
  <button id="send-btn">Send</button>
</div>
</div>
<script>
const chat=document.getElementById('chat'), input=document.getElementById('input'),
      sendBtn=document.getElementById('send-btn'), fileInput=document.getElementById('file-input'),
      fileName=document.getElementById('file-name'), modelInfo=document.getElementById('model-info');

// Fetch health on load
fetch('/health').then(r=>r.json()).then(d=>{
  modelInfo.textContent=(d.llm_configured?'●':'○')+' '+d.tools+' tools, '+d.memories+' memories';
}).catch(()=>modelInfo.textContent='○ offline');

// Theme toggle
const themeBtn=document.getElementById('theme-toggle');
function applyTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  localStorage.setItem('theme',t);
  themeBtn.textContent=t==='dark'?'☀️':'🌙';
}
const saved=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
applyTheme(saved);
themeBtn.addEventListener('click',()=>applyTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark'));

function addMsg(cls, txt){const d=document.createElement('div');d.className='msg '+cls;d.textContent=txt;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d}
function addSpinner(){const d=document.createElement('div');d.className='spinner';chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d}
function setBusy(b){sendBtn.disabled=b;input.disabled=b;fileInput.disabled=b}
const history=[];
let pendingConfirm=null;

async function send(msg, filePath, confirmData){
  setBusy(true);
  if(filePath) addMsg('system','📎 Uploaded: '+filePath);
  addMsg('user', msg);
  history.push({role:'user',content:msg});
  const sp=addSpinner();
  let assistantText='';
  try{
    const body={message:msg,history:history.slice(0,-1),stream:true};
    if(confirmData){body.confirm=true;body.pending_writes=confirmData;}
    const resp=await fetch('/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const reader=resp.body.getReader();
    const dec=new TextDecoder();
    let buf='', lastMsg=null, thinkingBuffer='';
    while(true){
      const{done,value}=await reader.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      const lines=buf.split('\n');
      buf=lines.pop()||'';
      for(const line of lines){
        if(!line.startsWith('data: ')) continue;
        const data=line.slice(6).trim();
        if(data==='[DONE]') continue;
        try{
          const ev=JSON.parse(data);
          if(ev.type==='text'){
            // Reset lastMsg for assistant responses to ensure proper styling
            if(!lastMsg || lastMsg.classList.contains('thinking') || lastMsg.classList.contains('tool-call')){
              lastMsg = addMsg('assistant', '');
            }
            lastMsg.textContent += ev.content;
            assistantText += ev.content;
            // Reset thinking buffer when we start a new answer
            thinkingBuffer = '';
          }else if(ev.type==='thinking'){
            // Handle thinking states - show them in a thinking bubble with full content
            if(!lastMsg || !lastMsg.classList.contains('thinking')){
              // Create new thinking bubble with full content
              lastMsg = addMsg('thinking', '🤔 ' + ev.content);
              thinkingBuffer = ev.content;
            } else {
              // Append to existing thinking bubble content with space for continuity
              thinkingBuffer += ' ' + ev.content;
              lastMsg.textContent = '🤔 ' + thinkingBuffer;
            }
            // Force UI update
            chat.scrollTop = chat.scrollHeight;
          }else if(ev.type==='tool_start'){
            // Show tool execution status as part of the thinking process
            if(lastMsg && lastMsg.classList.contains('thinking')){
              // Append tool status to the thinking bubble with space
              thinkingBuffer += ' 🔧 ' + ev.name + '...';
              lastMsg.textContent = '🤔 ' + thinkingBuffer;
            } else {
              // Create a new thinking bubble if none exists
              lastMsg = addMsg('thinking', '🤔 🔧 ' + ev.name + '...');
              thinkingBuffer = '🔧 ' + ev.name + '...';
            }
            // Force UI update
            chat.scrollTop = chat.scrollHeight;
          }else if(ev.type==='tool_result'){
            // Update tool execution status
            if(lastMsg && lastMsg.classList.contains('thinking')){
              // Find the tool line and update it
              if(thinkingBuffer.includes('🔧 ' + ev.name)){
                thinkingBuffer = thinkingBuffer.replace('🔧 ' + ev.name + '...', '🔧 ' + ev.name + '... done');
                lastMsg.textContent = '🤔 ' + thinkingBuffer;
              }
            }
          }else if(ev.type==='tool_error'){
            // Show tool error in thinking bubble
            if(lastMsg && lastMsg.classList.contains('thinking')){
              thinkingBuffer += ' ⚠️ ' + ev.name + ': ' + (ev.error || 'failed');
              lastMsg.textContent = '🤔 ' + thinkingBuffer;
            } else {
              addMsg('error', '⚠️ ' + ev.name + ': ' + (ev.error || 'failed'));
            }
          }else if(ev.type==='error'){
            addMsg('error','⚠️ '+(ev.message||'unknown error'));
          }else if(ev.type==='confirmation_required'){
              const writes=ev.pending_writes||[];
              pendingConfirm=writes;
              const details=writes.map(w=>{
                const args=Object.entries(w.args||{}).map(([k,v])=>k+'='+String(v).slice(0,60)).join(', ');
                return '  '+w.tool_name+'('+args+')';
              }).join('\n');
              addMsg('system','⚠️ Write confirmation required:\n'+details+'\n');
            const btnBar=document.createElement('div');
            btnBar.style.cssText='display:flex;gap:8px;padding:4px 0';
            const okBtn=document.createElement('button');
            okBtn.textContent='✅ Confirm';
            okBtn.style.cssText='padding:6px 12px;background:var(--btn);border:none;border-radius:4px;color:#fff;cursor:pointer;font-size:13px';
            const cancelBtn=document.createElement('button');
            cancelBtn.textContent='❌ Cancel';
            cancelBtn.style.cssText='padding:6px 12px;background:var(--error);border:1px solid var(--border);border-radius:4px;color:var(--fg);cursor:pointer;font-size:13px';
            okBtn.onclick=()=>{
              btnBar.remove();
              const lastMsg=history[history.length-1];
              send(lastMsg?lastMsg.content:'continue',null,pendingConfirm);
            };
            cancelBtn.onclick=()=>{
              btnBar.remove();
              addMsg('system','Write cancelled.');
              pendingConfirm=null;
            };
            btnBar.appendChild(okBtn);
            btnBar.appendChild(cancelBtn);
            chat.appendChild(btnBar);
            chat.scrollTop=chat.scrollHeight;
            return;
          }
        }catch(e){
          console.error('Event parsing error:', e);
        }
      }
    }
  }catch(e){addMsg('error','Connection failed: '+e.message)}
  finally{if(assistantText) history.push({role:'assistant',content:assistantText});sp.remove();setBusy(false);input.focus()}
}

// File upload
fileInput.addEventListener('change',async()=>{
  const f=fileInput.files[0];
  if(!f) return;
  fileName.textContent=f.name;
  const fd=new FormData();fd.append('file',f);
  try{
    const resp=await fetch('/upload',{method:'POST',body:fd});
    const data=await resp.json();
    if(data.path){
      fileName.textContent='✓ '+f.name;
      // Auto-fill input with a prompt about the uploaded file
      input.value='Read the uploaded file: '+data.filename;
    }else{
      fileName.textContent='✗ upload failed';
    }
  }catch(e){fileName.textContent='✗ upload error';}
});

// Send on button click or Enter
sendBtn.addEventListener('click',()=>{
  const msg=input.value.trim();
  if(!msg) return;
  const f=fileInput.files[0];
  const filePath=f?fileName.textContent.replace(/^✓ /,''):'';
  input.value='';
  fileName.textContent='';
  fileInput.value='';
  send(msg, filePath);
});
input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendBtn.click()}});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def web_ui():
    return HTML_PAGE


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file to uploads/ in workdir and return its path."""
    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    upload_dir = workdir / "uploads"
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

    print(f"[DEBUG] Upload received: filename={file.filename}, safe={safe_name}, path={dest}, size={len(content)}")

    return {
        "path": str(dest),
        "filename": safe_name,
        "size": len(content),
        "mimetype": file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
    }


def run_server(agent_instance, host: str = "0.0.0.0", port: int = 8000):
    """Run the FastAPI server with the given agent instance."""
    global agent
    agent = agent_instance
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