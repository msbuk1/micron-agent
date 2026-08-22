"""Core agent — ties together LLM, memory, skills, tools, and prompt building."""
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

from micron.llm import LLMBackend, LLMResponse, create_backend
from micron.memory import Memory
from micron.prompt import PromptBuilder
from micron.skills import SkillLoader
from micron.text_tool_parser import TextToolCallParser
from micron.tools.registry import ToolRegistry


def _availability_hint(backend, provider: str) -> str:
    """Suffix for the set_backend failure message when the API key looks wrong."""
    api_key = getattr(backend, "api_key", "")
    if provider in ("openrouter", "openai") and not api_key:
        return " (missing API key — set it in micron.yaml or env)"
    if api_key.startswith("<") and api_key.endswith(">"):
        return " (API key is a placeholder — replace it in micron.yaml)"
    return ""


@dataclass
class ToolCall:
    name: str
    args: dict
    call_id: str
    is_write: bool = False


@dataclass
class AgentConfig:
    context_dir: str = "context"
    provider: str = "llamacpp"
    model: str | None = None
    temperature: float = 0.1
    max_tokens: int = 2048
    max_tool_iterations: int = 8
    use_text_tool_parsing: bool = False
    llm_kwargs: dict = field(default_factory=dict)


# ── internal modules (not part of external seam) ───────────────────────

class _HistoryCompactor:
    """Pure history compression — mirrors previous _compress_history."""

    def __init__(self, keep_recent: int = 8):
        self.keep_recent = keep_recent

    def compress(self, history: list[dict], keep_recent: int | None = None) -> list[dict]:
        keep = keep_recent if keep_recent is not None else self.keep_recent
        if len(history) <= keep:
            return history
        old = history[:-keep]
        recent = history[-keep:]
        parts: list[str] = []
        for msg in old:
            role = msg["role"]
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")
            if tool_calls:
                content = f"[used tools: {', '.join(tc['function']['name'] for tc in tool_calls)}]"
            elif tool_call_id:
                content = f"[tool result] {content[:100]}"
            elif len(content) > 200:
                content = content[:200] + "..."
            parts.append(f"{role}: {content}")
        summary = "Previous conversation summary:\n" + "\n".join(parts)
        return [{"role": "user", "content": summary}] + recent

    def should_compress(self, history: list[dict] | None) -> bool:
        return bool(history and len(history) > 12)


class _LoopController:
    """Owns tool-loop state: iteration count, failure pivot, loop detection."""

    def __init__(self, max_iterations: int = 8):
        self.max_iterations = max_iterations
        self.tool_history: list[tuple[str, frozenset]] = []
        self.consecutive_failures: int = 0

    def reset(self, max_iterations: int | None = None) -> None:
        if max_iterations is not None:
            self.max_iterations = max_iterations
        self.tool_history.clear()
        self.consecutive_failures = 0

    def detect_loop(self, calls: list["ToolCall"]) -> bool:
        fingerprints: list[tuple[str, frozenset]] = []
        for tc in calls:
            args_frozen = frozenset((k, str(v)) for k, v in sorted(tc.args.items()))
            fingerprints.append((tc.name, args_frozen))
        if len(fingerprints) != len(set(fingerprints)):
            return True
        self.tool_history.extend(fingerprints)
        if len(self.tool_history) >= 6:
            last6 = self.tool_history[-6:]
            if len(set(last6)) <= 2:
                return True
        return False

    def record_result(self, has_errors: bool) -> str | None:
        if has_errors:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0
        if self.consecutive_failures >= 3:
            self.consecutive_failures = 0
            return (
                "You have failed 3 times in a row. STOP and think differently. "
                "Your current approach is not working. Try a completely different strategy "
                "or tell the user you cannot complete this task."
            )
        return None


class MicronAgent:
    """Lightweight AI agent with file-based memory, skills, and tool calling.

    Deep module — external seam is small (run/ask + injected backend). Loop
    control lives in internal _LoopController/_HistoryCompactor, not at the
    seam. Accepts dependencies, doesn't create them when the caller injects
    them (local-substitutable Memory/SkillLoader/ToolRegistry via tmp_path
    in tests, Remote-but-owned LLMBackend port with FakeLLM adapter).
    """

    def __init__(
        self,
        config: AgentConfig | LLMBackend | None = None,
        *args,
        backend: LLMBackend | None = None,
        memory: Memory | None = None,
        skills: SkillLoader | None = None,
        tools: ToolRegistry | None = None,
        prompt: PromptBuilder | None = None,
        **kwargs,
    ):
        # ── ergonomic C compat: MicronAgent(backend=FakeLLM, config=..., memory=...)
        #    and legacy MicronAgent(AgentConfig(...)) both work
        if isinstance(config, LLMBackend) and backend is None and not args:
            # MicronAgent(fake_backend) positional
            backend = config
            config = None
        elif args and isinstance(args[0], LLMBackend) and backend is None:
            backend = args[0]
        # Detect legacy backend= via llm_kwargs
        legacy_backend = None
        if config is not None and isinstance(config, AgentConfig) and "backend" in config.llm_kwargs:
            legacy_backend = config.llm_kwargs.get("backend")
        if backend is None:
            backend = legacy_backend
        # Build/normalize AgentConfig
        if config is None or isinstance(config, LLMBackend):
            # case: MicronAgent(backend=...) without config, or MicronAgent(fake) handled above
            if isinstance(config, LLMBackend):
                config = None
            config = AgentConfig(**kwargs) if isinstance(config, type(None)) else config
            # kwargs may contain context_dir etc when called as MicronAgent(backend, context_dir=...)
            if kwargs and isinstance(config, AgentConfig):
                # merge any leftover kwargs into config (e.g. context_dir from ergonomic call)
                for k, v in list(kwargs.items()):
                    if hasattr(config, k):
                        # frozen dataclass — rebuild
                        d = dict(config.__dict__)
                        d.update({k: v for k, v in kwargs.items() if k in d})
                        config = AgentConfig(**d)
                        break
        elif isinstance(config, dict):
            config = AgentConfig(**config)
        elif not isinstance(config, AgentConfig):
            # config is something else (e.g. LLMBackend handled)
            config = AgentConfig(**kwargs) if kwargs else AgentConfig()
        # If backend was also passed as llm_kwargs backend, prefer explicit backend param
        if backend is not None and isinstance(config, AgentConfig) and "backend" in config.llm_kwargs:
            # pop to avoid double-create; explicit wins
            try:
                config = AgentConfig(
                    context_dir=config.context_dir,
                    provider=config.provider,
                    model=config.model,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    max_tool_iterations=config.max_tool_iterations,
                    use_text_tool_parsing=config.use_text_tool_parsing,
                    llm_kwargs={k: v for k, v in config.llm_kwargs.items() if k != "backend"},
                )
            except Exception:
                pass
        self.config = config

        self.context_dir = Path(config.context_dir)
        self.context_dir.mkdir(parents=True, exist_ok=True)

        # Local-substitutable — inject or create
        self.memory = memory if memory is not None else Memory(self.context_dir / "memory")
        self.skills = skills if skills is not None else SkillLoader(self.context_dir / "skills")
        self.tools = tools if tools is not None else ToolRegistry()
        if tools is None:
            from micron.tools.decorator import _registry
            for td in _registry:
                self.tools.register(
                    name=td.name, func=td.func, description=td.description,
                    parameters=td.parameters, write=td.write,
                )
        # LLMBackend port — inject or create
        if backend is not None:
            self.llm = backend
        elif "backend" in getattr(config, "llm_kwargs", {}):
            self.llm = config.llm_kwargs.pop("backend")  # type: ignore[attr-defined]
        else:
            self.llm = create_backend(config.provider, config.model, **config.llm_kwargs)
        # Default to text-tool format for local models, off for API backends.
        provider = getattr(config, "provider", "llamacpp").lower()
        # honour explicit use_text_tool_parsing or llm_kwargs flag
        self.use_text_tool_format = getattr(config, "use_text_tool_parsing", False) or config.llm_kwargs.get(
            "use_text_tool_format", provider in ("llamacpp", "ollama")
        )
        self.provider = provider
        self.model = config.model

        self.prompt_builder = prompt if prompt is not None else PromptBuilder(
            self.context_dir, self.memory, self.skills,
            use_text_tool_format=self.use_text_tool_format,
            tools=self.tools,
        )

        self.skills.load_all()
        self._register_skill_tools()
        self._load_plugins()
        # Internal modules — not part of external seam
        self._loop = _LoopController(max_iterations=config.max_tool_iterations)
        self._compactor = _HistoryCompactor(keep_recent=8)

    # Backward-compat shims: tests access agent._tool_history / _consecutive_failures directly
    # These proxy to _loop so both views stay in sync.
    @property
    def _tool_history(self):  # type: ignore[no-redef]
        return self._loop.tool_history

    @_tool_history.setter
    def _tool_history(self, value):  # type: ignore[no-redef]
        self._loop.tool_history = value

    @property
    def _consecutive_failures(self):  # type: ignore[no-redef]
        return self._loop.consecutive_failures

    @_consecutive_failures.setter
    def _consecutive_failures(self, value):  # type: ignore[no-redef]
        self._loop.consecutive_failures = value

    def _register_skill_tools(self):
        """No longer registers tools from `.md` skill files.

        After the Skills/Tools split, all tools are defined via the shared
        `@tool` decorator in code (`builtin.py` + plugins) and seeded into the
        ToolRegistry at startup from ``micron.tools.decorator._registry``.
        Markdown files no longer gate tool existence. This method is retained
        as a no-op hook for backwards compatibility.
        """

    def _load_plugins(self):
        """Discover and register plugin tools from context/plugins/."""
        from micron.plugins.loader import discover_plugins

        plugin_dir = self.context_dir / "plugins"
        descriptors = discover_plugins(plugin_dir)
        for td in descriptors:
            # Add as a synthetic Skill so it appears in the tool schema list
            self.skills.add_plugin(td)
            # Register the function in ToolRegistry
            self.tools.register(
                name=td.name,
                func=td.func,
                description=td.description,
                parameters=td.parameters or {"type": "object", "properties": {}},
                write=td.write,
            )
            print(f"[plugin] Loaded: {td.name}")

    def register_tool(self, name: str, func, description: str, parameters: dict, write: bool = False):
        self.tools.register(name, func, description, parameters, write)

    def run(
        self, message: str, history: list[dict] | None = None, stream: bool = True,
        confirm: bool = False, pending_tool_calls: list[ToolCall] | None = None,
    ) -> Generator[dict, None, None]:
        if not self.llm.is_available():
            yield {"type": "error", "message": "LLM backend not available."}
            yield {"type": "done"}
            return

        if confirm and pending_tool_calls:
            # Execute confirmed writes
            tool_results = []
            for chunk in self._execute_tool_calls(pending_tool_calls, user_message=message):
                if chunk["type"] in ("tool_result", "tool_error"):
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": chunk["call_id"],
                        "name": chunk["name"],
                        "content": chunk.get("summary", chunk.get("error", "")),
                    })
                yield chunk

            # Continue conversation with tool results in history
            if tool_results:
                # Build messages with the tool results appended
                system_prompt = self.prompt_builder.build_system_prompt(message)
                messages = [{"role": "system", "content": system_prompt}]
                if history:
                    if self._compactor.should_compress(history):
                        history = self._compactor.compress(history)
                    for msg in history[-20:]:
                        messages.append(msg)
                # Add the user message and tool results
                messages.append({"role": "user", "content": message})
                messages.extend(tool_results)

                # Continue the conversation
                yield from self._run_with_messages(messages, skip_write_confirm=True)
            return

        self._loop.reset(max_iterations=self.config.max_tool_iterations)
        system_prompt = self.prompt_builder.build_system_prompt(message)
        messages = [{"role": "system", "content": system_prompt}]

        # Compress history if too long (summarize old turns)
        if self._compactor.should_compress(history):
            history = self._compactor.compress(history)

        if history:
            for msg in history[-20:]:
                messages.append(msg)
        messages.append({"role": "user", "content": message})

        yield from self._run_with_messages(messages)

    def _run_with_messages(self, messages: list[dict], skip_write_confirm: bool = False) -> Generator[dict, None, None]:
        """Run the tool loop with pre-built messages.

        Args:
            skip_write_confirm: If True, execute write tools directly without
                requiring user confirmation.  Used after the user has already
                confirmed one write in the current turn.
        """
        tool_iterations = 0
        tools_used_this_turn = False
        pending_calls: list[ToolCall] = []

        while tool_iterations < self.config.max_tool_iterations:
            full_text = ""
            pending_calls = []
            # TextToolCallParser owns the streaming buffer (one per iteration).
            # Constructed only when the local text-tool format is in use; for
            # API backends the LLM yields native tool_call events and the
            # text stream is safe to surface verbatim.
            text_parser = (
                TextToolCallParser(self.tools.schemas())
                if self.use_text_tool_format
                else None
            )

            for response in self.llm.stream_chat(
                messages=messages,
                tools=self.tools.schemas(),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ):
                if response.type == "text":
                    full_text += response.content
                    if text_parser:
                        yield from self._consume_parser_events(
                            text_parser.feed(response.content),
                            pending_calls,
                            tools_used_this_turn,
                        )
                    else:
                        yield {"type": "text", "content": response.content}
                elif response.type == "reasoning":
                    yield {"type": "thinking", "content": response.content}
                elif response.type == "tool_call":
                    pending_calls.append(ToolCall(
                        name=response.tool_name,
                        args=response.tool_args or {},
                        call_id=response.tool_call_id or f"call_{len(pending_calls)}",
                        is_write=self._is_write_tool(response.tool_name),
                    ))
                    yield {"type": "tool_start", "name": response.tool_name, "call_id": pending_calls[-1].call_id}
                elif response.type == "done":
                    if text_parser:
                        yield from self._consume_parser_events(
                            text_parser.flush(),
                            pending_calls,
                            tools_used_this_turn,
                        )
                    break
                elif response.type == "error":
                    yield {"type": "error", "message": response.content}
                    yield {"type": "done"}
                    return

            if not pending_calls:
                yield {"type": "done"}
                return

            if self._loop.detect_loop(pending_calls):
                yield {"type": "error", "message": "Loop detected. Stopping."}
                yield {"type": "done"}
                return

            read_calls = [c for c in pending_calls if not c.is_write]
            write_calls = [c for c in pending_calls if c.is_write]

            if read_calls:
                tools_used_this_turn = True

                # Build the proper assistant message with tool_calls array.
                assistant_message: dict = {"role": "assistant", "content": full_text if full_text else None}
                if read_calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in read_calls
                    ]
                messages.append(assistant_message)

                has_errors = False
                for tc in read_calls:
                    try:
                        result = self.tools.call(tc.name, **tc.args)
                        summary = self._summarize_result(result)
                        # Check if the tool returned an error string
                        is_error = isinstance(result, str) and result.startswith("Error:")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "name": tc.name,
                            "content": summary,
                        })
                        if is_error:
                            has_errors = True
                            yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": summary}
                        else:
                            yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": summary, "result": result}
                    except Exception as e:
                        friendly = self._friendly_error(tc.name, e)
                        has_errors = True
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "name": tc.name,
                            "content": f"Error: {friendly}",
                        })
                        yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": friendly}

                pivot = self._loop.record_result(has_errors)
                if pivot:
                    messages.append({"role": "user", "content": pivot})

                tool_iterations += 1
                continue

            if write_calls:
                # For write tools, emit confirmation_required event and pause
                # This allows the caller (CLI or server) to handle confirmation
                tools_used_this_turn = True
                assistant_message: dict = {"role": "assistant", "content": full_text if full_text else None}
                assistant_message["tool_calls"] = [
                    {"id": tc.call_id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                    for tc in write_calls
                ]
                messages.append(assistant_message)
                
                # Emit confirmation_required event with pending write calls
                pending_writes = [
                    {"tool_name": tc.name, "args": tc.args, "call_id": tc.call_id}
                    for tc in write_calls
                ]
                yield {"type": "confirmation_required", "pending_writes": pending_writes}
                
                # Add tool_start events for consistency
                for tc in write_calls:
                    yield {"type": "tool_start", "name": tc.name, "call_id": tc.call_id}

                tool_iterations += 1
                yield {"type": "done"}
                return

        yield {"type": "done"}

    def _execute_tool_calls(self, calls: list[ToolCall], user_message: str = "") -> Generator[dict, None, None]:
        """Execute confirmed write tool calls and return tool results for history."""
        tool_results = []
        for tc in calls:
            try:
                result = self.tools.call(tc.name, **tc.args)
                summary = self._summarize_result(result)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "name": tc.name,
                    "content": summary,
                })
                yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": summary, "result": result}
            except Exception as e:
                friendly = self._friendly_error(tc.name, e)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "name": tc.name,
                    "content": f"Error: {friendly}",
                })
                yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": friendly}
        # Return tool_results by attaching to the generator (hacky but works)
        self._last_tool_results = tool_results

    def _friendly_error(self, tool_name: str, error: Exception) -> str:
        """Convert a tool error into a user-friendly message."""
        from micron.error_format import format_error

        # format_error prefixes "Error: "; agent loop strips it for tool_error event
        msg = format_error(error, tool=tool_name)
        return msg.removeprefix("Error: ").lstrip()

    def _summarize_result(self, result: Any, max_len: int = 1000) -> str:
        if isinstance(result, (dict, list)):
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = str(result)
        return text[:max_len] + ("..." if len(text) > max_len else "")

    def _consume_parser_events(
        self,
        events,
        pending_calls: list[ToolCall],
        tools_used_this_turn: bool,
    ) -> Generator[dict, None, None]:
        """Translate TextToolCallParser events into agent events.

        The parser is suppressed once a read tool has been called in this
        turn — the model is responding to the tool result, not planning
        new tool calls. Text events are still emitted; tool_call events
        are dropped.
        """
        for event in events:
            if event["type"] == "text":
                yield {"type": "text", "content": event["content"]}
            elif event["type"] == "tool_call":
                if tools_used_this_turn:
                    continue
                pending_calls.append(ToolCall(
                    name=event["name"],
                    args=event["args"],
                    call_id=event["call_id"],
                    is_write=self._is_write_tool(event["name"]),
                ))
                yield {
                    "type": "tool_start",
                    "name": event["name"],
                    "call_id": event["call_id"],
                }

    def _is_write_tool(self, name: str) -> bool:
        return self.tools.is_write(name)

    def _detect_loop(self, calls: list[ToolCall]) -> bool:
        return self._loop.detect_loop(calls)

    def _compress_history(self, history: list[dict], keep_recent: int = 8) -> list[dict]:
        """Compress old history by summarizing tool results into a single summary turn."""
        return self._compactor.compress(history, keep_recent=keep_recent)

    def _continue_conversation(self, user_message: str, history: list[dict] | None = None) -> Generator[dict, None, None]:
        yield from self.run(user_message, history=history)

    def add_memory(self, text: str, tags: list[str] | None = None, importance: int = 3) -> str:
        return self.memory.add(text, tags=tags, importance=importance)

    def search_memory(self, query: str, k: int = 5, tags: list[str] | None = None) -> list:
        return self.memory.search(query, k=k, tags=tags)

    def list_memories(self, n: int = 20) -> list:
        return self.memory.list(n=n)

    def reload_skills(self):
        self.skills.reload()
        self._register_skill_tools()

    def unload_model(self):
        """Unload the LLM model from memory."""
        if hasattr(self.llm, 'unload'):
            self.llm.unload()

    # — ergonomic C aliases — progressive disclosure, not on first screen
    def close(self) -> None:
        """Ergonomic alias for unload_model."""
        self.unload_model()

    def ask(self, query: str, history: list[dict] | None = None) -> str:
        """One-liner for the 80% non-streaming case: run + collect text.

        Hides process_events behind the seam so CLI/server non-stream branches
        collapse to a single call. Still yields tool errors as part of text.
        """
        from micron.events import process_events

        result = process_events(self.run(query, history=history))
        return result.text

    def confirm(
        self,
        writes: list[dict],
        *,
        query: str = "",
        history: list[dict] | None = None,
    ) -> Generator[dict, None, None]:
        """Resume after a confirmation_required event.

        Thin wrapper around run(confirm=True, pending_tool_calls=...).
        """
        calls = [
            ToolCall(
                name=w["tool_name"],
                args=w.get("args", {}),
                call_id=w.get("call_id", f"confirm_{i}"),
                is_write=True,
            )
            for i, w in enumerate(writes)
        ]
        yield from self.run(query, history=history, confirm=True, pending_tool_calls=calls)

    def reconfigure(self, provider: str, model: str, **kwargs) -> None:
        """Ergonomic alias for set_backend."""
        self.set_backend(provider, model, **kwargs)

    def set_backend(self, provider: str, model: str, **kwargs) -> None:
        """Switch to a new LLM provider/model at runtime.

        Unloads the old backend (if it supports ``unload()``), creates a
        new one via :func:`micron.llm.create_backend`, and updates the
        agent's ``provider``/``model``/``llm`` fields plus the
        ``use_text_tool_format`` flag and ``prompt_builder`` so the next
        ``run()`` uses the new backend.

        Raises ``ValueError`` if the provider is unknown, or the backend
        constructor / ``is_available()`` call fails — the agent is left
        on its previous backend in that case.
        """
        provider = provider.lower()
        # Build & validate new backend before touching any state, so a
        # failed swap doesn't leave the agent with a half-changed config.
        new_llm = create_backend(provider, model, **kwargs)
        if not new_llm.is_available():
            raise RuntimeError(
                f"{provider} backend for {model!r} is not available"
                f"{_availability_hint(new_llm, provider)}"
            )

        # Unload old backend (best-effort; some backends have no unload)
        if self.llm is not None and hasattr(self.llm, "unload"):
            try:
                self.llm.unload()
            except Exception:
                pass

        self.llm = new_llm
        self.provider = provider
        self.model = model
        self.config.provider = provider
        self.config.model = model
        # Recompute the text-tool flag (mirrors __init__ logic).
        self.use_text_tool_format = self.config.llm_kwargs.get(
            "use_text_tool_format", provider in ("llamacpp", "ollama")
        )
        # PromptBuilder captures use_text_tool_format at construction.
        self.prompt_builder = PromptBuilder(
            self.context_dir, self.memory, self.skills,
            use_text_tool_format=self.use_text_tool_format,
            tools=self.tools,
        )


def create_agent(**kwargs) -> MicronAgent:
    # Ergonomic factory — supports both legacy AgentConfig(**kwargs) and
    # direct injection: create_agent(backend=fake, memory=..., tools=...)
    # Extract injectable seams if provided as kwargs.
    inject_keys = {"backend", "memory", "skills", "tools", "prompt"}
    injected = {k: kwargs.pop(k) for k in list(kwargs.keys()) if k in inject_keys}
    # Also handle llm_kwargs backend passed via Config-style call
    if "backend" not in injected and "llm_kwargs" in kwargs and isinstance(kwargs["llm_kwargs"], dict) and "backend" in kwargs["llm_kwargs"]:
        injected["backend"] = kwargs["llm_kwargs"].pop("backend")
    if injected:
        cfg = AgentConfig(**kwargs) if kwargs else AgentConfig()
        return MicronAgent(cfg, **injected)
    return MicronAgent(AgentConfig(**kwargs))