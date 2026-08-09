"""CLI entry point for micron agent."""
import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from micron.agent import AgentConfig, MicronAgent
from micron.config import Config
from micron.events import process_events
from micron.sessions import SessionLogger
from micron.text_tool_parser import strip_tool_call_markup


def create_agent_and_logger(
    config: Config,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[MicronAgent, SessionLogger, str]:
    """Create agent, backend, and session logger from a Config object."""
    from micron.llm import create_backend

    rt = config.resolve_runtime(
        provider_override=provider,
        model_override=model,
    )
    if temperature is not None:
        rt["temperature"] = temperature
    if max_tokens is not None:
        rt["max_tokens"] = max_tokens

    backend_kwargs = {
        "n_threads": rt["n_threads"],
        "n_gpu_layers": rt["n_gpu_layers"],
        "n_ctx": rt["n_ctx"],
    }
    if rt.get("api_key"):
        backend_kwargs["api_key"] = rt["api_key"]
    if rt.get("base_url"):
        backend_kwargs["base_url"] = rt["base_url"]

    backend = create_backend(
        rt["provider"],
        rt["model"],
        **backend_kwargs,
    )

    agent = MicronAgent(AgentConfig(
        context_dir=rt["context_dir"],
        provider=rt["provider"],
        model=rt["model"],
        temperature=rt["temperature"],
        max_tokens=rt["max_tokens"],
        max_tool_iterations=rt["max_tool_iterations"],
        llm_kwargs={**backend_kwargs, "backend": backend},
    ))
    sessions_dir = Path(agent.context_dir) / "sessions"
    logger = SessionLogger(sessions_dir)
    session_id = logger.start_session()
    return agent, logger, session_id


class ThinkingIndicator:
    """Shows 'Thinking...' with growing dots while the agent processes.

    When the first thinking event arrives, the dots stop permanently and a
    single 'Thinking...' line stays visible. Once the thinking phase ends,
    the full reasoning text prints as a single block.
    """

    def __init__(self):
        self._stop = threading.Event()
        self._thinking_started = threading.Event()
        self._thread = None
        self._thinking_text = ""

    def start(self):
        self._stop.clear()
        self._thinking_started.clear()
        self._thinking_text = ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Flush accumulated thinking text, then clear the line."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.flush()
        sys.stderr.write("\r" + " " * 40 + "\r")
        sys.stderr.flush()

    def update(self, text: str):
        """Accumulate thinking text. Dots stop on first call; full text prints on stop()."""
        if self._stop.is_set():
            return
        # First thinking event: kill the dots thread
        if not self._thinking_started.is_set():
            self._thinking_started.set()
            sys.stderr.write("\r" + " " * 40 + "\r")
            sys.stderr.flush()
            blue = "\033[34m" if sys.stderr.isatty() else ""
            reset = "\033[0m" if sys.stderr.isatty() else ""
            sys.stderr.write(f"{blue}  Thinking...{reset}\n")
            sys.stderr.flush()
        self._thinking_text += text

    def flush(self):
        """Print the accumulated thinking text as a block, then reset."""
        text = self._thinking_text.strip()
        self._thinking_text = ""
        if text:
            blue = "\033[34m" if sys.stderr.isatty() else ""
            reset = "\033[0m" if sys.stderr.isatty() else ""
            print(f"\n{blue}  Thinking:\n{text}{reset}\n", file=sys.stderr)

    def _run(self):
        dots = 0
        while not self._stop.is_set() and not self._thinking_started.is_set():
            dots = (dots % 3) + 1
            sys.stderr.write(f"\rThinking{'.' * dots}  ")
            sys.stderr.flush()
            time.sleep(0.5)


def _strip_thinking(text: str) -> str:
    """Remove thinking tags, tool call markup, and looping text from model output."""
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'<thinking>.*', '', text, flags=re.DOTALL)
    # Tool-call markup is stripped by the shared parser (single source of
    # truth for what tool-call syntax looks like). <thinking> tags and the
    # line-dedup below stay here — those are display concerns, not parser
    # concerns.
    text = strip_tool_call_markup(text)
    # Remove repeated lines (model looping)
    lines = text.split('\n')
    clean_lines = []
    seen = Counter()
    for line in lines:
        stripped_line = line.strip()
        if stripped_line and seen[stripped_line] >= 2:
            continue
        clean_lines.append(line)
        seen[stripped_line] += 1
    text = '\n'.join(clean_lines).strip()
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="micron — lightweight AI agent")
    parser.add_argument("query", nargs="*", help="Query to run (omit to launch TUI)")
    parser.add_argument("--server", action="store_true", help="Run HTTP server")
    parser.add_argument("--host", default=None, help="Server host (default from config)")
    parser.add_argument("--port", type=int, default=None, help="Server port (default from config)")
    parser.add_argument("--provider", help="LLM provider override")
    parser.add_argument("--model", help="Model path/name override")
    parser.add_argument("--temperature", type=float, help="Temperature override")
    parser.add_argument("--max-tokens", type=int, help="Max tokens override")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    parser.add_argument("--list-tools", action="store_true", help="List available tools and exit")
    parser.add_argument("--list-memories", action="store_true", help="List recent memories and exit")
    parser.add_argument("--add-memory", type=str, help="Add a memory and exit")
    parser.add_argument("--search-memory", type=str, help="Search memories and exit")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    config = Config()  # single loader — reads micron.yaml + env + defaults

    # Ensure context directories exist
    context_dir = Path(config.get("context_dir", "context"))
    for sub in ("skills", "memory", "knowledge", "persona"):
        (context_dir / sub).mkdir(exist_ok=True)

    # Create agent and session logger
    agent, logger, session_id = create_agent_and_logger(
        config,
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    print(f"Session: {session_id}")
    if args.server:
        rt = config.resolve_runtime()
        host = args.host or rt.get("host", "[IP_ADDRESS]")
        port = args.port or rt.get("port", 8000)
        from micron.server import run_server
        run_server(agent, host=host, port=port)
        return

    if args.list_tools:
        tools = agent.tools.list()
        print(json.dumps(tools, indent=2))
        return

    if args.list_memories:
        memories = agent.list_memories(20)
        for m in memories:
            print(f"[{m.id[:8]}] {m.text[:80]}... (tags: {m.tags})")
        return

    if args.add_memory:
        mid = agent.add_memory(args.add_memory)
        print(f"Added memory: {mid}")
        return

    if args.search_memory:
        results = agent.search_memory(args.search_memory, k=5)
        for r in results:
            print(f"[{r.id[:8]}] score=0 {r.text[:80]}...")
        return

    # Build query
    if args.query:
        query = " ".join(args.query)
    else:
        query = None

    # Run agent
    if query is None:
        from micron.tui.app import MicronTUI
        def factory():
            return create_agent_and_logger(
                config,
                provider=args.provider,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
        MicronTUI(factory).run()
    else:
        run_query(agent, logger, query, args.no_stream)


def run_query(agent, logger, query: str, no_stream: bool = False):
    """Run a single query and print results."""
    thinking = ThinkingIndicator()
    thinking.start()

    def on_text(t):
        thinking.stop()
        print(t, end="", flush=True)

    def on_thinking(t):
        thinking.update(t)

    def on_tool_start(name, call_id):
        thinking.stop()
        print(f"\n[Using: {name}]", file=sys.stderr)

    def on_tool_result(name, summary):
        thinking.stop()
        print(f"\n[{name} done]", file=sys.stderr)

    def on_tool_error(name, error):
        thinking.stop()
        print(f"\n[Error] {error}", file=sys.stderr)

    result = process_events(
        agent.run(query),
        on_text=on_text,
        on_thinking=on_thinking,
        on_tool_start=on_tool_start,
        on_tool_result=on_tool_result,
        on_tool_error=on_tool_error,
    )
    thinking.stop()
    cleaned = _strip_thinking(result.text)
    if cleaned:
        print(cleaned)
    logger.log_turn("assistant", cleaned or result.text)


if __name__ == "__main__":
    main()
