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
        self.llm = create_backend(config.provider, config.model, **config.llm_kwargs)
        self.prompt_builder = PromptBuilder(self.context_dir, self.memory, self.skills)

        self.skills.load_all()
        self._register_skill_tools()
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
            yield from self._execute_tool_calls(pending_tool_calls, message)
            yield from self._continue_conversation(message, history)
            return

        system_prompt = self.prompt_builder.build_system_prompt(message)
        messages = [{"role": "system", "content": system_prompt}]

        # Compress history if too long (summarize old turns)
        if history and len(history) > 12:
            history = self._compress_history(history)

        if history:
            for msg in history[-20:]:
                messages.append(msg)
        messages.append({"role": "user", "content": message})

        tool_iterations = 0
        tools_used_this_turn = False

        while tool_iterations < self.config.max_tool_iterations:
            full_text = ""
            pending_calls: list[ToolCall] = []

            for response in self.llm.stream_chat(
                messages=messages, tools=self.skills.schemas(),
                temperature=self.config.temperature, max_tokens=self.config.max_tokens,
            ):
                if response.type == "text":
                    full_text += response.content
                    yield {"type": "text", "content": response.content}
                elif response.type == "reasoning":
                    pass  # Skip reasoning — it's internal thinking, not the answer
                elif response.type == "tool_call":
                    pending_calls.append(ToolCall(
                        name=response.tool_name, args=response.tool_args or {},
                        call_id=response.tool_call_id or f"call_{len(pending_calls)}",
                        is_write=self._is_write_tool(response.tool_name),
                    ))
                    yield {"type": "tool_start", "name": response.tool_name, "call_id": pending_calls[-1].call_id}
                elif response.type == "done":
                    break
                elif response.type == "error":
                    yield {"type": "error", "message": response.content}
                    yield {"type": "done"}
                    return

            # Try text-based parsing ONLY if no tools used yet this turn
            if not pending_calls and full_text and not tools_used_this_turn:
                text_calls = self._parse_text_tool_calls(full_text)
                if text_calls:
                    pending_calls = text_calls

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
                messages.append({"role": "assistant", "content": full_text})

                tool_results = []
                has_errors = False
                for tc in read_calls:
                    try:
                        result = self.tools.call(tc.name, **tc.args)
                        summary = self._summarize_result(result)
                        tool_results.append(f"[{tc.name}] {summary}")
                        yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": summary, "result": result}
                    except Exception as e:
                        friendly = self._friendly_error(tc.name, e)
                        tool_results.append(f"[{tc.name}] Error: {friendly}")
                        yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": friendly}
                        has_errors = True

                # Track consecutive failures
                if has_errors:
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                # Pivot thought after 3 consecutive failures
                if self._consecutive_failures >= 3:
                    pivot = ("You have failed 3 times in a row. STOP and think differently. "
                             "Your current approach is not working. Try a completely different strategy "
                             "or tell the user you cannot complete this task.")
                    tool_results.append(f"\n[SYSTEM] {pivot}")
                    self._consecutive_failures = 0

                messages.append({"role": "user", "content": "Tool results:\n" + "\n".join(tool_results) + "\n\nProvide your final answer based on these results. Do not use any more tools."})

                tool_iterations += 1
                continue

            if write_calls:
                summaries = [{"tool_name": tc.name, "args": tc.args, "call_id": tc.call_id} for tc in write_calls]
                yield {"type": "confirmation_required", "pending_writes": summaries}
                yield {"type": "done"}
                return

    def _execute_tool_calls(self, calls: list[ToolCall], user_message: str = "") -> Generator[dict, None, None]:
        for tc in calls:
            try:
                result = self.tools.call(tc.name, **tc.args)
                summary = self._summarize_result(result)
                yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": summary, "result": result}
            except Exception as e:
                yield {"type": "tool_error", "name": tc.name, "call_id": tc.call_id, "error": self._friendly_error(tc.name, e)}

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
        calls = []
        tool_names = {t.name for t in self.tools.all()}

        # Format 1: name="tool_name"> name="param">value (prompt-driven)
        # Format 2: <function name="tool_name">...</function> (MiniCPM native)
        # Try both formats and use whichever finds results

        calls_format1 = self._parse_name_quote_format(text, tool_names)
        calls_format2 = self._parse_function_tag_format(text, tool_names)

        return calls_format1 or calls_format2

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
        """Parse <function name="tool">...</function> format (MiniCPM/Qwen native)."""
        calls = []
        # Match <function name="tool_name">optional content</function>
        for match in re.finditer(r'<function\s+name="(\w+)"[^>]*>(.*?)</function>', text, re.DOTALL):
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
                        args = {k: self._coerce_param(str(v), props.get(k, {})) for k, v in parsed.items() if k in param_names}
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

        # Summarize old turns
        parts = []
        for msg in old:
            role = msg["role"]
            content = msg.get("content", "")
            if len(content) > 200:
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
