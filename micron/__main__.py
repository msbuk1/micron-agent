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
from micron.events import process_events, EventType
from micron.sessions import SessionLogger
from micron.text_tool_parser import strip_tool_call_markup


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
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    # Tool-call markup is stripped by the shared parser (single source of
    # truth for what tool-call syntax looks like). <think> tags and the
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
    _active_skill = None  # Set by /skill command, consumed on next query

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
            print("  /trash       List deleted files (recoverable)")
            print("  /restore F   Restore a file from trash")
            print("  /purge       Empty trash permanently")
            print("  /undo F      Restore file from .bak backup")
            print("  /tree        Show directory tree (--depth=N --ext=EXT)")
            print("  /skill NAME  Load a procedure skill into context")
            print("  /skills      List available procedure skills")
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

        elif command == "trash":
            from micron.tools.builtin import list_trash
            result = list_trash()
            print(result)

        elif command == "restore":
            if not args:
                print("Usage: /restore <filename>")
                print("Use /trash to see available files")
                return True
            from micron.tools.builtin import restore_file
            result = restore_file(args[0])
            print(result)

        elif command == "purge":
            from micron.tools.builtin import purge_trash
            result = purge_trash()
            print(result)

        elif command == "undo":
            if not args:
                print("Usage: /undo <filename>")
                print("Restores file from .bak backup created by edit_file")
                return True
            from micron.tools.builtin import undo_file
            result = undo_file(args[0])
            print(result)


        elif command == "tree":
            from micron.tools.builtin import tree
            # Parse --depth and --ext from args
            max_depth = 3
            ext = None
            tree_path = '.'
            for arg in args:
                if arg.startswith('--depth='):
                    max_depth = int(arg.split('=')[1])
                elif arg.startswith('--ext='):
                    ext = arg.split('=')[1]
                else:
                    tree_path = arg
            result = tree(tree_path, max_depth=max_depth, ext=ext)
            print(result)

        elif command == "skill":
            if not args:
                print("Usage: /skill <name>")
                print("Use /skills to list available procedure skills")
                return True
            skill_name = args[0]
            found = agent.skills.get(skill_name)
            if not found:
                print(f"Skill '{skill_name}' not found.")
                return True
            if not found.procedure:
                print(f"'{skill_name}' is a tool skill, not a procedure skill.")
                return True
            _active_skill = found
            print(f"Loaded: {found.name}")
            print(f"Description: {found.description}")
            print(f"Content: {len(found.content)} chars")
            print("(Skill will be included in your next message)")

        elif command == "skills":
            procedures = [s for s in agent.skills.all() if s.procedure]
            if not procedures:
                print("No procedure skills loaded.")
            else:
                print(f"Procedure skills ({len(procedures)}):")
                for s in procedures:
                    print(f"  {s.name:30s} {s.description[:60]}")

        else:
            print(f"Unknown command: {command}. Try /help")

        return True

    known_commands = {"help", "?", "exit", "quit", "q", "clear", "mem", "tools", "model",
                      "h", "unload", "reload", "providers", "sessions", "resume", "last",
                      "trash", "restore", "purge", "undo", "tree", "skill", "skills"}

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

            # Inject active skill content if loaded via /skill
            if _active_skill:
                query = f"[Active skill: {_active_skill.name}]\n\n{_active_skill.content}\n\n---\n\nUser request: {query}"
                _active_skill = None  # One-shot injection

            # Normal query
            thinking = ThinkingIndicator()
            thinking.start()
            result = ""
            pending_writes = None

            def on_text(t):
                nonlocal result
                thinking.stop()
                result += t

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

            def on_confirmation_required(writes):
                nonlocal pending_writes
                thinking.stop()
                pending_writes = writes

            event_result = process_events(
                agent.run(query, history=history),
                on_text=on_text,
                on_thinking=on_thinking,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
                on_tool_error=on_tool_error,
                on_confirmation_required=on_confirmation_required,
            )
            pending_writes = pending_writes or event_result.pending_writes
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
                        confirmed = process_events(
                            agent.run(query, history=history, confirm=True, pending_tool_calls=calls),
                            on_tool_result=lambda name, s: print(f"\n[{name} done]", file=sys.stderr),
                            on_tool_error=lambda name, err: print(f"\n[Error] {err}", file=sys.stderr),
                        )
                        result = confirmed.text

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
