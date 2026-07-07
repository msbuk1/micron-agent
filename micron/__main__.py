"""CLI entry point for micron agent."""
import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from collections import Counter

import yaml
import re

from micron.agent import MicronAgent, AgentConfig, ToolCall, create_agent
from micron.sessions import SessionLogger


class ThinkingIndicator:
    """Shows 'Thinking...' with growing dots while the agent processes."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        # Clear the line
        sys.stderr.write("\r" + " " * 40 + "\r")
        sys.stderr.flush()

    def _run(self):
        dots = 0
        while not self._stop.is_set():
            dots = (dots % 3) + 1
            sys.stderr.write(f"\rThinking{'.' * dots}  ")
            sys.stderr.flush()
            time.sleep(0.5)


def _strip_thinking(text: str) -> str:
    """Remove thinking tags, tool call markup, and looping text from model output."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    text = re.sub(r'<function\s+name="\w+"[^>]*>.*?</function>', '', text, flags=re.DOTALL)
    text = re.sub(r'\n?\s*name="\w+">(?:\s+name="\w+">[^\n]*)*', '', text)
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


def load_config(args: argparse.Namespace | None = None, config_path: str = None) -> dict:
    """Load config from micron.yaml with env var overrides."""
    if config_path is None:
        candidates = [
            Path("micron.yaml"),
            Path(__file__).parent.parent / "micron.yaml",
        ]
        for c in candidates:
            if c.exists():
                config_path = str(c)
                break

    config = {}
    if config_path:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    defaults = {
        "context_dir": "context",
        "temperature": 0.1,
        "max_tokens": 2048,
        "max_tool_iterations": 8,
        "firecrawl_url": "http://localhost:3002",
        "workdir": "/home/matt",
    }
    for k, v in defaults.items():
        config.setdefault(k, v)

    # Resolve provider config
    default_provider = config.get("default_provider", "llamacpp")
    providers = config.get("providers", {})
    selected = (args.provider if args else None) or os.environ.get("MICRON_PROVIDER") or default_provider

    if selected not in providers:
        print(f"[WARN] Unknown provider '{selected}', falling back to {default_provider}", file=sys.stderr)
        selected = default_provider

    prov_cfg = providers.get(selected, {})
    config["provider"] = selected
    config["model"] = (args.model if args else None) or prov_cfg.get("model")
    config["api_key"] = prov_cfg.get("api_key")
    config["base_url"] = prov_cfg.get("base_url")
    config.setdefault("n_threads", prov_cfg.get("n_threads", 8))
    config.setdefault("n_gpu_layers", prov_cfg.get("n_gpu_layers", 0))
    config.setdefault("n_ctx", prov_cfg.get("n_ctx", 8192))

    # CLI env var overrides config file
    if "FIRECRAWL_URL" not in os.environ:
        os.environ["FIRECRAWL_URL"] = config["firecrawl_url"]
    if "MICRON_WORKDIR" not in os.environ:
        os.environ["MICRON_WORKDIR"] = config["workdir"]
    if "MICRON_CONTEXT_DIR" not in os.environ:
        # Resolve context_dir relative to the project root
        project_root = Path(__file__).parent.parent
        os.environ["MICRON_CONTEXT_DIR"] = str(project_root / config["context_dir"])
    if "MICRON_PROVIDER" not in os.environ:
        os.environ["MICRON_PROVIDER"] = selected

    return config


def parse_args(argv: list[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="micron — lightweight AI agent")
    parser.add_argument("query", nargs="*", help="Query to run (omit for interactive mode)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Run in interactive mode")
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
    config = load_config(args)

    # CLI overrides for non-provider settings
    if args.temperature:
        config["temperature"] = args.temperature
    if args.max_tokens:
        config["max_tokens"] = args.max_tokens

    # Ensure context directories exist
    context_dir = Path(config["context_dir"])
    for sub in ("skills", "memory", "knowledge", "persona"):
        (context_dir / sub).mkdir(exist_ok=True)

    # Create backend
    from micron.llm import create_backend

    backend_kwargs = {
        "n_threads": config.get("n_threads", 8),
        "n_gpu_layers": config.get("n_gpu_layers", 0),
        "n_ctx": config.get("n_ctx", 8192),
    }
    if config.get("api_key"):
        backend_kwargs["api_key"] = config["api_key"]
    if config.get("base_url"):
        backend_kwargs["base_url"] = config["base_url"]

    backend = create_backend(
        config["provider"],
        config["model"],
        **backend_kwargs,
    )

    agent = MicronAgent(AgentConfig(
        context_dir=config["context_dir"],
        provider=config["provider"],
        model=config["model"],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
        max_tool_iterations=config["max_tool_iterations"],
        llm_kwargs=backend_kwargs,
    ))
    sessions_dir = Path(agent.context_dir) / "sessions"
    logger = SessionLogger(sessions_dir)
    session_id = logger.start_session()
    print(f"Session: {session_id}")
    if args.server:
        host = args.host or config.get("host", "0.0.0.0")
        port = args.port or config.get("port", 8000)
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
    elif args.interactive:
        query = None
    else:
        parser = argparse.ArgumentParser()
        parse_args(["--help"])
        return

    # Run agent
    if args.interactive or query is None:
        run_interactive(agent, args.no_stream)
    else:
        run_query(agent, query, args.no_stream)


def run_query(agent, query: str, no_stream: bool = False):
    """Run a single query and print results."""
    thinking = ThinkingIndicator()
    thinking.start()

    if no_stream:
        result = ""
        for chunk in agent.run(query):
            if chunk["type"] == "text":
                if not result:
                    thinking.stop()
                result += chunk["content"]
            elif chunk["type"] == "tool_call":
                thinking.stop()
                print(f"\n[Tool: {chunk['tool_name']}] {chunk['tool_args']}", file=sys.stderr)
            elif chunk["type"] == "tool_result":
                thinking.stop()
                print(f"\n[Result] {chunk['summary']}", file=sys.stderr)
            elif chunk["type"] == "tool_error":
                thinking.stop()
                err = chunk.get("error", "unknown error")
                print(f"\n[Error] {err}", file=sys.stderr)
        thinking.stop()
        print(_strip_thinking(result))
    else:
        result = ""
        for chunk in agent.run(query):
            if chunk["type"] == "text":
                if not result:
                    thinking.stop()
                result += chunk["content"]
            elif chunk["type"] == "tool_call":
                thinking.stop()
                print(f"\n[Tool: {chunk['tool_name']}] {chunk['tool_args']}", file=sys.stderr)
            elif chunk["type"] == "tool_result":
                thinking.stop()
                print(f"\n[Result] {chunk['summary']}", file=sys.stderr)
            elif chunk["type"] == "tool_error":
                thinking.stop()
                err = chunk.get("error", "unknown error")
                print(f"\n[Error] {err}", file=sys.stderr)
        thinking.stop()
        cleaned = _strip_thinking(result)
        print(cleaned)
        logger.log_turn("assistant", cleaned or result)


def run_interactive(agent, no_stream: bool = False):
    """Run interactive chat loop with history, slash commands, and session logging."""
    print("micron interactive mode (type '/help' for commands)")
    print("=" * 40)
    history: list[dict] = []

    # Session logging
    sessions_dir = Path(agent.context_dir) / "sessions"
    logger = SessionLogger(sessions_dir)
    session_id = logger.start_session()
    print(f"Session: {session_id}")

    def handle_command(cmd: str) -> bool:
        parts = cmd[1:].strip().split()
        command = parts[0].lower()
        args = parts[1:]

        if command in ("exit", "quit", "q"):
            return False

        elif command in ("help", "?", "h"):
            print("Commands:")
            print("  /help, /?    Show this help")
            print("  /exit, /quit Exit")
            print("  /clear       Clear conversation history")
            print("  /mem         List recent memories")
            print("  /tools       Show available tools")
            print("  /model       Show current model info")
            print("  /providers   List available providers from config")
            print("  /unload      Unload model from memory (frees RAM)")
            print("  /reload      Reload skills from disk")
            print("  /sessions    List recent sessions")
            print("  /resume ID   Resume a previous session")
            print("  /last        Show last assistant response")
            print("")
            print("Just type your message to chat with the agent.")

        elif command == "clear":
            history.clear()
            print("Conversation history cleared.")

        elif command == "mem":
            memories = agent.list_memories(10)
            if not memories:
                print("No memories stored.")
            else:
                print(f"Recent memories ({len(memories)}):")
                for m in memories:
                    tags = " ".join(f"#{t}" for t in m.tags) if m.tags else ""
                    print(f"  [{m.id[:8]}] {m.text[:80]} {tags}")

        elif command == "tools":
            tools = agent.tools.list()
            if not tools:
                print("No tools available.")
            else:
                print(f"Available tools ({len(tools)}):")
                for t in tools:
                    write_tag = " [write]" if t.get("write", False) else ""
                    print(f"  {t['name']}: {t['description']}{write_tag}")

        elif command == "model":
            llm = agent.llm
            print(f"Provider: {llm.__class__.__name__}")
            if hasattr(llm, '_init_kwargs'):
                print(f"Config: {json.dumps(llm._init_kwargs, indent=2, default=str)}")

        elif command == "unload":
            agent.unload_model()
            print("Model unloaded from memory.")

        elif command == "reload":
            before = len(agent.skills.all())
            agent.reload_skills()
            after = len(agent.skills.all())
            print(f"Skills reloaded ({before} → {after}).")

        elif command == "providers":
            cfg = load_config()
            providers = cfg.get("providers", {})
            default = cfg.get("default_provider", "llamacpp")
            active = os.environ.get("MICRON_PROVIDER", default)
            print(f"Default: {default}  Active: {active}")
            for name, prov_cfg in providers.items():
                model = prov_cfg.get("model", "(no model set)")
                marker = " ← active" if name == active else ""
                print(f"  {name}: {model}{marker}")

        elif command == "sessions":
            sessions = logger.list_sessions(10)
            if not sessions:
                print("No sessions found.")
            else:
                print("Recent sessions:")
                for s in sessions:
                    print(f"  {s['id']}  {s['turns']} turns  {s['size'] // 1024}KB")

        elif command == "resume":
            if not args:
                print("Usage: /resume <session_id>")
                return True
            resume_id = args[0]
            resumed = logger.get_session_context(resume_id)
            if not resumed:
                print(f"Session '{resume_id}' not found.")
                return True
            history.clear()
            history.extend(resumed)
            print(f"Resumed session {resume_id} ({len(resumed)} turns loaded).")

        elif command == "last":
            if history:
                last_msg = history[-1]
                print(f"[{last_msg['role']}]: {last_msg['content'][:500]}")
            else:
                print("No messages yet.")

        else:
            print(f"Unknown command: {command}. Try /help")

        return True

    known_commands = {"help", "?", "exit", "quit", "q", "clear", "mem", "tools", "model",
                      "h", "unload", "reload", "providers", "sessions", "resume", "last"}

    try:
        while True:
            try:
                query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not query:
                continue

            # Handle slash commands
            if query.startswith("/"):
                first_word = query[1:].strip().split()[0].lower() if query[1:].strip() else ""
                if first_word in known_commands:
                    if not handle_command(query):
                        break
                    continue

            # Log user turn
            logger.log_turn("user", query)

            # Normal query
            thinking = ThinkingIndicator()
            thinking.start()
            result = ""
            pending_writes = None
            for chunk in agent.run(query, history=history):
                if chunk["type"] == "text":
                    if not result:
                        thinking.stop()
                    result += chunk["content"]
                elif chunk["type"] == "tool_call":
                    thinking.stop()
                    print(f"\n[Using: {chunk['tool_name']}]", file=sys.stderr)
                elif chunk["type"] == "tool_result":
                    thinking.stop()
                    tool = chunk.get("name", "")
                    print(f"\n[{tool} done]", file=sys.stderr)
                elif chunk["type"] == "confirmation_required":
                    thinking.stop()
                    pending_writes = chunk.get("pending_writes", [])
                    break
                elif chunk["type"] == "tool_error":
                    thinking.stop()
                    print(f"\n[Error] {chunk.get('error', 'unknown')}", file=sys.stderr)
                elif chunk["type"] == "done":
                    break
            thinking.stop()

            # Confirm and execute write tools
            if pending_writes:
                # Ask user for confirmation
                for w in pending_writes:
                    tool_name = w["tool_name"]
                    args = w.get("args", {})
                    if tool_name == "write_file":
                        print(f"\n[Write file: {args.get('path', '?')}]", file=sys.stderr)
                    elif tool_name == "write_knowledge":
                        print(f"\n[Write knowledge: {args.get('title', '?')}]", file=sys.stderr)
                    else:
                        print(f"\n[Write: {tool_name}({args})]", file=sys.stderr)

                try:
                    confirm = input("Proceed? [Y/n] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    confirm = "n"

                if confirm in ("n", "no", ""):
                    print("Cancelled.", file=sys.stderr)
                    result = "Write operation cancelled by user."
                else:
                    calls = []
                    for w in pending_writes:
                        calls.append(ToolCall(
                            name=w["tool_name"], args=w.get("args", {}),
                            call_id=w.get("call_id", f"confirm_{len(calls)}"),
                            is_write=True,
                        ))
                    if calls:
                        result = ""
                        confirmed_chunks = agent.run(query, history=history, confirm=True, pending_tool_calls=calls)
                        for chunk in confirmed_chunks:
                            if chunk["type"] == "text":
                                result += chunk["content"]
                            elif chunk["type"] == "tool_result":
                                tool = chunk.get("name", "")
                                print(f"\n[{tool} done]", file=sys.stderr)
                            elif chunk["type"] == "tool_error":
                                print(f"\n[Error] {chunk.get('error', 'unknown')}", file=sys.stderr)
                            elif chunk["type"] == "done":
                                break

            cleaned = _strip_thinking(result)
            if cleaned:
                print(cleaned)

            # Log assistant turn
            logger.log_turn("assistant", cleaned or result)

            # Track conversation history
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": cleaned or result})

    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        logger.end_session()


if __name__ == "__main__":
    main()
