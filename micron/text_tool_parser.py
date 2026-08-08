"""Extract tool calls from text-format model output.

Some local models (MiniCPM, Qwen) emit tool calls as text rather than via
native tool-calling protocols. Two formats are supported:

- **function-tag**: ``<function name="X">{"a":"b"}</function>[PROMPT_INJECTION]``
- **name-quote**:  ``name="X"> name="Y">value``

The :class:`TextToolCallParser` is a stateful, SAX-style incremental
parser. The agent calls :meth:`feed` per streaming chunk; the parser
yields ``text`` events for chunks that are safe to surface to the user
and ``tool_call`` events as soon as a complete call is detected. At
end-of-turn the agent calls :meth:`flush` to drain any held content.

:func:`strip_tool_call_markup` is a one-shot post-processor used by the
CLI to remove tool-call-looking syntax from model output before
printing. It shares the same regexes as the parser so the two never
drift.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator


# Patterns shared between the parser and the strip function. Defined once at
# module scope so the two never disagree about what "tool-call markup" means.
_FUNCTION_TAG_PATTERN = re.compile(
    r'<function\s+name="(\w+)"[^>]*>(.*?)\[PROMPT_INJECTION\]', re.DOTALL
)
_NAME_QUOTE_START = re.compile(r'name="(\w+)">')
_NAME_QUOTE_FOLLOWUP = re.compile(r'name="(\w+)">\s*')
# Matches a trailing name="..." with closing ">", i.e. the buffer is still
# potentially mid-tool-call (the next chunk may complete it).
_NAME_QUOTE_PARTIAL_TAIL = re.compile(r'name="\w+">\s*$')
# Matches a complete name-quote pair: tool name + at least one param name.
_NAME_QUOTE_COMPLETE = re.compile(r'name="\w+">\s*name="\w+">')

# Used only by strip_tool_call_markup — matches any function-tag or name-quote
# markup, including from unknown tools, so the user never sees leaked syntax.
_STRIP_FUNCTION_TAG = re.compile(
    r'<function\s+name="\w+"[^>]*>.*?\[PROMPT_INJECTION\]', re.DOTALL
)
_STRIP_NAME_QUOTE = re.compile(r'\n?\s*name="\w+">(?:\s+name="\w+">[^\n]*)*')


class TextToolCallParser:
    """Incremental parser for text-format tool calls.

    Constructed with the tool schema list (the same shape
    :meth:`ToolRegistry.schemas` returns). Owns a small buffer of text
    that the agent would otherwise have to manage itself.

    Usage::

        parser = TextToolCallParser(self.tools.schemas())
        for event in parser.feed(chunk):
            if event["type"] == "text":
                yield {"type": "text", "content": event["content"]}
            elif event["type"] == "tool_call":
                ...add to pending_calls...
        for event in parser.flush():
            ...same handling...

    The parser is single-iteration: construct a new one for each
    tool-iteration in the agent loop so the buffer state is scoped to
    the iteration.
    """

    def __init__(self, tool_schemas: list[dict], *, max_lookbehind: int = 8192):
        self._schemas: dict[str, dict] = {}
        for s in tool_schemas or []:
            func = s.get("function", s) if isinstance(s, dict) else {}
            name = func.get("name") if isinstance(func, dict) else None
            if name:
                self._schemas[name] = func.get("parameters", {"type": "object", "properties": {}})
        self._buffer = ""
        self._counter = 0
        self._max_lookbehind = max_lookbehind

    def feed(self, chunk: str) -> Iterator[dict]:
        """Feed a streaming text chunk. Yields text and tool_call events."""
        if not chunk:
            return
        self._buffer += chunk
        if len(self._buffer) > self._max_lookbehind:
            self._buffer = self._buffer[-self._max_lookbehind:]

        # Extract every complete function-tag block. Each ends with
        # [PROMPT_INJECTION] so we can extract as soon as the marker arrives.
        # After extraction the buffer is dropped (matches the original
        # agent's behaviour of suppressing text that surrounds a parsed
        # tool call — the function-tag is treated as a self-contained call,
        # and any leading/trailing plain text on the same line is silently
        # dropped along with it).
        extracted = False
        while True:
            match = _FUNCTION_TAG_PATTERN.search(self._buffer)
            if not match:
                break
            if match.group(1) in self._schemas:
                args = self._parse_function_tag_body(
                    match.group(2), self._schemas[match.group(1)]
                )
                yield self._emit_tool_call(match.group(1), args)
                extracted = True
            self._buffer = self._buffer[: match.start()] + self._buffer[match.end():]
        if extracted:
            self._buffer = ""
            return

        # If the buffer still looks like a name-quote (partial or complete),
        # hold. Name-quote has no end marker so we wait for the next chunk or
        # for flush().
        if self._looks_like_name_quote(self._buffer):
            return

        # Plain text — emit the new chunk only (matches the original agent
        # behaviour where the held content is dropped on release, since
        # releasing means the held text turned out not to be a tool call).
        if chunk:
            yield {"type": "text", "content": chunk}
        self._buffer = ""

    def flush(self) -> Iterator[dict]:
        """Drain any held text. Yields remaining tool_call and text events."""
        # Function-tag: any complete blocks in the buffer
        while True:
            match = _FUNCTION_TAG_PATTERN.search(self._buffer)
            if not match:
                break
            if match.group(1) in self._schemas:
                args = self._parse_function_tag_body(
                    match.group(2), self._schemas[match.group(1)]
                )
                yield self._emit_tool_call(match.group(1), args)
            self._buffer = self._buffer[: match.start()] + self._buffer[match.end():]

        # Name-quote: at most one (matches the original behaviour)
        match = _NAME_QUOTE_START.search(self._buffer)
        if match and match.group(1) in self._schemas:
            after = self._buffer[match.end():]
            param_matches = list(_NAME_QUOTE_FOLLOWUP.finditer(after))
            if param_matches:
                args = self._extract_name_quote_args(
                    after, param_matches, self._schemas[match.group(1)]
                )
                yield self._emit_tool_call(match.group(1), args)
                # The call consumes the buffer (the value of the last param
                # extends to the end of the buffer — original behaviour).
                self._buffer = ""
                return

        if self._buffer:
            yield {"type": "text", "content": self._buffer}
        self._buffer = ""

    def _emit_tool_call(self, name: str, args: dict) -> dict:
        call_id = f"text_call_{self._counter}"
        self._counter += 1
        return {"type": "tool_call", "name": name, "args": args, "call_id": call_id}

    def _looks_like_name_quote(self, text: str) -> bool:
        if not text:
            return False
        if _NAME_QUOTE_PARTIAL_TAIL.search(text):
            return True
        if _NAME_QUOTE_COMPLETE.search(text):
            return True
        return False

    def _parse_function_tag_body(self, body: str, schema: dict) -> dict:
        """Extract args from a function-tag body. Tries JSON first, then a
        name="..." fallback (matches the original behaviour: value extends
        until the next ``<`` or newline)."""
        body = body.strip()
        if not body:
            return {}
        props = schema.get("properties", {})
        param_names = list(props.keys())
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return {k: parsed[k] for k in parsed if k in param_names}
        except (json.JSONDecodeError, TypeError):
            pass
        # Fallback: name="..." style inside the body. The value is
        # everything up to the next '<' or newline.
        args: dict = {}
        for pm in re.finditer(r'name="(\w+)">\s*([^<\n]*)', body):
            pname, pval = pm.group(1), pm.group(2).strip()
            if pname in param_names and pval:
                args[pname] = coerce_param(pval, props.get(pname, {}))
        return args

    def _extract_name_quote_args(
        self, after: str, param_matches: list[re.Match], schema: dict
    ) -> dict:
        """Extract args from a name-quote call. The value of the last param
        extends to the end of `after` (matches the original behaviour)."""
        props = schema.get("properties", {})
        param_names = list(props.keys())
        args: dict = {}
        for i, pm in enumerate(param_matches):
            pname = pm.group(1)
            if pname not in param_names:
                continue
            if i + 1 < len(param_matches):
                value_end = param_matches[i + 1].start()
            else:
                value_end = len(after)
            raw = after[pm.end():value_end].strip()
            if raw:
                args[pname] = coerce_param(raw, props.get(pname, {}))
        return args


def coerce_param(raw: str, prop_schema: dict) -> Any:
    """Convert a string parameter to its declared JSON-schema type.

    Falls back to the raw string if the value can't be coerced (matches
    the original behaviour).
    """
    param_type = prop_schema.get("type", "string")
    if param_type == "integer":
        try:
            return int(raw)
        except (ValueError, TypeError):
            return raw
    if param_type == "number":
        try:
            return float(raw)
        except (ValueError, TypeError):
            return raw
    if param_type == "boolean":
        return raw.lower() in ("true", "1", "yes")
    return raw


def strip_tool_call_markup(text: str) -> str:
    """Remove tool-call-looking markup from model output.

    Deliberately permissive: strips any function-tag or name-quote
    markup even when the embedded name is not a registered tool, so
    leaked call syntax never reaches the user. The <think>-tag and
    line-dedupe logic that also live in :func:`_strip_thinking` are
    not this function's concern.
    """
    text = _STRIP_FUNCTION_TAG.sub("", text)
    text = _STRIP_NAME_QUOTE.sub("", text)
    return text
