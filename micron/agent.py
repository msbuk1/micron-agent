"""Core agent — ties together LLM, memory, skills, tools, and prompt building."""
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

from micron.llm import LLMBackend, LLMResponse, create_backend
from micron.memory import Memory
from micron.prompt import PromptBuilder
from micron.skills import SkillLoader
from micron.tools.registry import ToolRegistry


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


class MicronAgent:
    """Lightweight AI agent with file-based memory, skills, and tool calling."""

    def __init__(self, config: AgentConfig | None = None, **kwargs):
        if config is None:
            config = AgentConfig(**kwargs)
        self.config = config

        self.context_dir = Path(config.context_dir)
        self.context_dir.mkdir(parents=True, exist_ok=True)

        self.memory = Memory(self.context_dir / "memory")
        self.skills = SkillLoader(self.context_dir / "skills")
        self.tools = ToolRegistry()
        # Use pre-built backend if provided, otherwise create one
        if "backend" in config.llm_kwargs:
            self.llm = config.llm_kwargs.pop("backend")
        else:
            self.llm = create_backend(config.provider, config.model, **config.llm_kwargs)
        # Default to text-tool format for local models, off for API backends.
        provider = getattr(config, "provider", "llamacpp").lower()
        self.use_text_tool_format = config.llm_kwargs.get("use_text_tool_format", provider in ("llamacpp", "ollama"))

        self.prompt_builder = PromptBuilder(
            self.context_dir, self.memory, self.skills,
            use_text_tool_format=self.use_text_tool_format,
        )

        self.skills.load_all()
        self._register_skill_tools()
        self._load_plugins()
        self._tool_history: list[tuple[str, frozenset]] = []
        self._consecutive_failures = 0

    def _register_skill_tools(self):
        for skill in self.skills.all():
            if skill.module:
                try:
                    mod = __import__(skill.module, fromlist=[skill.name])
                    func = getattr(mod, skill.name)
                    self.tools.register(
                        name=skill.name, func=func, description=skill.description,
                        parameters=skill.parameters, write=skill.write,
                    )
                except (ImportError, AttributeError) as e:
                    print(f"[WARN] Could not load tool {skill.name} from {skill.module}: {e}")

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
                    if len(history) > 12:
                        history = self._compress_history(history)
                    for msg in history[-20:]:
                        messages.append(msg)
                # Add the user message and tool results
                messages.append({"role": "user", "content": message})
                messages.extend(tool_results)

                # Continue the conversation
                yield from self._run_with_messages(messages, skip_write_confirm=True)
            return

        self._consecutive_failures = 0
        self._tool_history.clear()
        system_prompt = self.prompt_builder.build_system_prompt(message)
        messages = [{"role": "system", "content": system_prompt}]

        # Compress history if too long (summarize old turns)
        if history and len(history) > 12:
            history = self._compress_history(history)

        if history:
            for msg in history[-20:]:
                messages.append(msg)
        messages.append({"role": "user", "content": message})

        yield from self._run_with_messages(messages)

    def _looks_like_tool_call(self, text: str) -> bool:
            """Check if text buffer ends with a complete tool call pattern."""
            if not text:
                return False
            # Check for <function name="..."> pattern
            if '<function name="' in text and '[PROMPT_INJECTION]' in text:
                return True
            # Check for name="tool"> pattern
            if re.search(r'name="\w+">\s*$', text):
                return True
            # Check for name="tool"> name="param">value pattern
            if re.search(r'name="\w+">\s*name="\w+">', text):
                return True
            return False

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
            # Buffer for suppressing tool-call markup from text output
            text_buffer = ""

            for response in self.llm.stream_chat(
                messages=messages,
                tools=self.skills.schemas(),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ):
                if response.type == "text":
                    full_text += response.content
                    text_buffer += response.content

                    # If we're using text tool format, check if buffer contains tool call markup
                    # If so, don't emit it as text (we'll parse and emit tool events instead)
                    if self.use_text_tool_format:
                        # Check if buffer ends with a complete tool call pattern
                        if self._looks_like_tool_call(text_buffer):
                            # Don't emit the tool call markup - we'll parse it below
                            continue

                    yield {"type": "text", "content": response.content}
                    text_buffer = ""  # Clear buffer after emitting
                elif response.type == "reasoning":
                    pass
                elif response.type == "tool_call":
                    pending_calls.append(ToolCall(
                        name=response.tool_name,
                        args=response.tool_args or {},
                        call_id=response.tool_call_id or f"call_{len(pending_calls)}",
                        is_write=self._is_write_tool(response.tool_name),
                    ))
                    yield {"type": "tool_start", "name": response.tool_name, "call_id": pending_calls[-1].call_id}
                elif response.type == "done":
                    # Flush any remaining clean text
                    if text_buffer and not self._looks_like_tool_call(text_buffer):
                        yield {"type": "text", "content": text_buffer}
                    break
                elif response.type == "error":
                    yield {"type": "error", "message": response.content}
                    yield {"type": "done"}
                    return

            # Only use text-based parsing when configured (local/text models).
            if not pending_calls and full_text and self.use_text_tool_format and not tools_used_this_turn:
                text_calls = self._parse_text_tool_calls(full_text)
                if text_calls:
                    pending_calls = text_calls
                    # Replay tool_start events for parsed text calls
                    for tc in text_calls:
                        yield {"type": "tool_start", "name": tc.name, "call_id": tc.call_id}

            if not pending_calls:
                yield {"type": "done"}
                return

            if self._detect_loop(pending_calls):
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

                if has_errors:
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                if self._consecutive_failures >= 3:
                    pivot = (
                        "You have failed 3 times in a row. STOP and think differently. "
                        "Your current approach is not working. Try a completely different strategy "
                        "or tell the user you cannot complete this task."
                    )
                    messages.append({"role": "user", "content": pivot})
                    self._consecutive_failures = 0

                tool_iterations += 1
                continue

            if write_calls:
                # Execute write tools directly — workdir is a sandbox
                tools_used_this_turn = True
                assistant_message: dict = {"role": "assistant", "content": full_text if full_text else None}
                assistant_message["tool_calls"] = [
                    {"id": tc.call_id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                    for tc in write_calls
                ]
                messages.append(assistant_message)
                for tc in write_calls:
                    try:
                        result = self.tools.call(tc.name, **tc.args)
                        summary = self._summarize_result(result)
                        messages.append({"role": "tool", "tool_call_id": tc.call_id, "name": tc.name, "content": summary})
                        yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": summary, "result": result}
                    except Exception as e:
                        friendly = self._friendly_error(tc.name, e)
                        messages.append({"role": "tool", "tool_call_id": tc.call_id, "name": tc.name, "content": f"Error: {friendly}"})
                        yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": friendly}
                tool_iterations += 1
                continue

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
        msg = str(error)
        # Common error patterns
        if isinstance(error, FileNotFoundError):
            return f"File not found. Check the path and try again."
        elif isinstance(error, PermissionError):
            return f"Permission denied. You don't have access to that file."
        elif isinstance(error, TimeoutError):
            return f"Operation timed out. Try again or use a shorter query."
        elif "connection" in msg.lower():
            return f"Connection error. The service may be down or unreachable."
        elif "timeout" in msg.lower():
            return f"Request timed out. Try again later."
        elif "not found" in msg.lower():
            return f"Not found: {msg[:80]}"
        elif "invalid" in msg.lower() or "bad" in msg.lower():
            return f"Invalid input: {msg[:80]}"
        return f"{tool_name} failed: {msg[:120]}"

    def _summarize_result(self, result: Any, max_len: int = 1000) -> str:
        if isinstance(result, (dict, list)):
            text = json.dumps(result, ensure_ascii=False)
        else:
            text = str(result)
        return text[:max_len] + ("..." if len(text) > max_len else "")

    def _is_write_tool(self, name: str) -> bool:
        return self.tools.is_write(name)

    def _detect_loop(self, calls: list[ToolCall]) -> bool:
        fingerprints = []
        for tc in calls:
            args_frozen = frozenset((k, str(v)) for k, v in sorted(tc.args.items()))
            fingerprints.append((tc.name, args_frozen))
        if len(fingerprints) != len(set(fingerprints)):
            return True
        self._tool_history.extend(fingerprints)
        if len(self._tool_history) >= 6:
            last6 = self._tool_history[-6:]
            if len(set(last6)) <= 2:
                return True
        return False

    def _parse_text_tool_calls(self, text: str) -> list[ToolCall]:
        """Parse tool calls from MiniCPM/Qwen text output."""
        tool_names = {t.name for t in self.tools.all()}

        # Format 1: name="tool_name"> name="param">value (prompt-driven)
        # Format 2: <function name="tool_name">...[PROMPT_INJECTION] (MiniCPM native)
        # Try format 2 first as it handles JSON properly
        calls_format2 = self._parse_function_tag_format(text, tool_names)
        calls_format1 = self._parse_name_quote_format(text, tool_names)

        return calls_format2 or calls_format1

    def _parse_name_quote_format(self, text: str, tool_names: set) -> list[ToolCall]:
        """Parse name=\"tool\"> name=\"param\">value format."""
        calls = []
        for match in re.finditer(r'name="(\w+)">', text):
            tool_name = match.group(1)
            if tool_name not in tool_names:
                continue

            tool = self.tools.get(tool_name)
            if not tool:
                continue

            props = tool.parameters.get("properties", {}) if tool.parameters else {}
            param_names = list(props.keys())

            after = text[match.end():]
            param_positions = [(m.start(), m.end(), m.group(1)) for m in re.finditer(r'name="(\w+)">\s*', after)]
            args = {}
            for i, (start, end, pname) in enumerate(param_positions):
                if pname not in param_names:
                    continue
                if i + 1 < len(param_positions):
                    value_end = param_positions[i + 1][0]
                else:
                    value_end = len(after)
                raw = after[end:value_end].strip()
                if raw:
                    args[pname] = self._coerce_param(raw, props.get(pname, {}))

            required = tool.parameters.get("required", []) if tool.parameters else []
            if not args and not required:
                args = {}

            # Always add the call — even with empty args — so errors surface
            calls.append(ToolCall(
                name=tool_name, args=args, call_id=f"text_call_{len(calls)}",
                is_write=self._is_write_tool(tool_name),
            ))
            break
        return calls

    def _parse_function_tag_format(self, text: str, tool_names: set) -> list[ToolCall]:
        """Parse <function name="tool">...[PROMPT_INJECTION] format (MiniCPM/Qwen native)."""
        calls = []
        # Match <function name="tool_name">optional content[PROMPT_INJECTION]
        for match in re.finditer(r'<function\s+name="(\w+)"[^>]*>(.*?)\[PROMPT_INJECTION\]', text, re.DOTALL):
            tool_name = match.group(1)
            if tool_name not in tool_names:
                continue

            tool = self.tools.get(tool_name)
            if not tool:
                continue

            body = match.group(2).strip()
            props = tool.parameters.get("properties", {}) if tool.parameters else {}
            param_names = list(props.keys())
            args = {}

            if body:
                # Try JSON first
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        args = {k: parsed[k] for k in parsed if k in param_names}
                except (json.JSONDecodeError, TypeError):
                    # Fall back to name="param">value extraction within the body
                    for pm in re.finditer(r'name="(\w+)">\s*([^<\n]*)', body):
                        pname, pval = pm.group(1), pm.group(2).strip()
                        if pname in param_names and pval:
                            args[pname] = self._coerce_param(pval, props.get(pname, {}))

            required = tool.parameters.get("required", []) if tool.parameters else []
            if not args and not required:
                args = {}

            # Always add the call — even with empty args — so errors surface
            calls.append(ToolCall(
                name=tool_name, args=args, call_id=f"text_call_{len(calls)}",
                is_write=self._is_write_tool(tool_name),
            ))
        return calls

    def _coerce_param(self, raw: str, prop_schema: dict) -> Any:
        """Convert a string parameter to its schema type."""
        param_type = prop_schema.get("type", "string")
        if param_type == "integer":
            try: return int(raw)
            except (ValueError, TypeError): return raw
        elif param_type == "number":
            try: return float(raw)
            except (ValueError, TypeError): return raw
        elif param_type == "boolean":
            return raw.lower() in ("true", "1", "yes")
        return raw

    def _compress_history(self, history: list[dict], keep_recent: int = 8) -> list[dict]:
        """Compress old history by summarizing tool results into a single summary turn."""
        if len(history) <= keep_recent:
            return history

        old = history[:-keep_recent]
        recent = history[-keep_recent:]

        # Summarize old turns, preserving assistant/tool message pairs
        parts = []
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


def create_agent(**kwargs) -> MicronAgent:
    return MicronAgent(AgentConfig(**kwargs))