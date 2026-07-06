"""LLM backends — llama.cpp, Ollama, OpenAI-compatible APIs."""
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generator, Optional


@dataclass
class LLMResponse:
    type: str  # "text", "tool_call", "reasoning", "done", "error"
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_call_id: Optional[str] = None


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Generator[LLMResponse, None, None]:
        """Stream chat completion with optional tool calling."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is ready."""
        pass


class LlamaCppBackend(LLMBackend):
    """llama.cpp backend via llama-cpp-python."""

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 8192,
        n_threads: int = 8,
        n_gpu_layers: int = 0,
        verbose: bool = False,
        **kwargs,
    ):
        self.model_path = model_path
        self._llm = None
        self._init_kwargs = {
            "model_path": model_path,
            "n_ctx": n_ctx,
            "n_threads": n_threads,
            "n_gpu_layers": n_gpu_layers,
            "verbose": verbose,
            **kwargs,
        }

    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(**self._init_kwargs)

    def is_available(self) -> bool:
        return os.path.exists(self.model_path)

    def unload(self):
        """Unload the model from memory."""
        if self._llm is not None:
            try:
                self._llm.close()
            except Exception:
                pass
            self._llm = None

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Generator[LLMResponse, None, None]:
        self._load()

        # Build tool schema for llama.cpp
        tool_schemas = None
        if tools:
            tool_schemas = [t["function"] for t in tools]

        # llama.cpp create_chat_completion with tools
        stream = self._llm.create_chat_completion(
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto" if tools else "none",
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        tool_call_buffer: dict = {}

        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})

            if "content" in delta and delta["content"]:
                yield LLMResponse(type="text", content=delta["content"])

            if "tool_calls" in delta and delta["tool_calls"]:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_call_buffer:
                        tool_call_buffer[idx] = {
                            "id": tc.get("id", f"call_{idx}"),
                            "name": "",
                            "arguments": "",
                        }
                    if "function" in tc:
                        if "name" in tc["function"]:
                            tool_call_buffer[idx]["name"] = tc["function"]["name"]
                        if "arguments" in tc["function"]:
                            tool_call_buffer[idx]["arguments"] += tc["function"]["arguments"]

        # Emit tool calls
        for buf in tool_call_buffer.values():
            if buf["name"]:
                try:
                    args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield LLMResponse(
                    type="tool_call",
                    tool_name=buf["name"],
                    tool_args=args,
                    tool_call_id=buf["id"],
                )

        yield LLMResponse(type="done")


class OllamaBackend(LLMBackend):
    """Ollama HTTP API backend."""

    def __init__(
        self,
        model: str = "smollm2:1.7b",
        base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            self._available = resp.status_code == 200
            return self._available
        except Exception:
            self._available = False
            return False

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Generator[LLMResponse, None, None]:
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [t["function"] for t in tools]

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        tool_calls_buffer: list[dict] = []

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode())
            except json.JSONDecodeError:
                continue

            msg = data.get("message", {})

            if "content" in msg and msg["content"]:
                yield LLMResponse(type="text", content=msg["content"])

            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    tool_calls_buffer.append({
                        "id": tc.get("id", f"call_{len(tool_calls_buffer)}"),
                        "name": tc["function"]["name"],
                        "arguments": tc["function"].get("arguments", "{}"),
                    })

            if data.get("done", False):
                break

        for tc in tool_calls_buffer:
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            yield LLMResponse(
                type="tool_call",
                tool_name=tc["name"],
                tool_args=args,
                tool_call_id=tc["id"],
            )

        yield LLMResponse(type="done")


class OpenAICompatibleBackend(LLMBackend):
    """Generic OpenAI-compatible API backend (OpenRouter, vLLM, LM Studio, etc.)."""

    def __init__(
        self,
        model: str = "openrouter/free",
        api_key: str = "",
        base_url: str = "https://openrouter.ai/api/v1",
        **kwargs,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        if not self.api_key:
            self._available = False
            return False
        try:
            import requests
            resp = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5,
            )
            self._available = resp.status_code == 200
            return self._available
        except Exception:
            self._available = False
            return False

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Generator[LLMResponse, None, None]:
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            stream=True,
            timeout=300,
        )
        resp.raise_for_status()

        tool_calls_buffer: dict[int, dict] = {}

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode()
            if not line.startswith("data: "):
                continue
            if line.strip() == "data: [DONE]":
                break

            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            choices = data.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})

            if "content" in delta and delta["content"]:
                yield LLMResponse(type="text", content=delta["content"])

            # Reasoning models (ornith, deepseek-r1, etc.) put output in reasoning_content
            if "reasoning_content" in delta and delta["reasoning_content"]:
                yield LLMResponse(type="reasoning", content=delta["reasoning_content"])

            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.get("id", f"call_{idx}"),
                            "name": "",
                            "arguments": "",
                        }
                    if "function" in tc:
                        if "name" in tc["function"]:
                            tool_calls_buffer[idx]["name"] = tc["function"]["name"]
                        if "arguments" in tc["function"]:
                            tool_calls_buffer[idx]["arguments"] += tc["function"]["arguments"]

        for buf in tool_calls_buffer.values():
            if buf["name"]:
                try:
                    args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield LLMResponse(
                    type="tool_call",
                    tool_name=buf["name"],
                    tool_args=args,
                    tool_call_id=buf["id"],
                )

        yield LLMResponse(type="done")


def create_backend(provider: str, model: str, **kwargs) -> LLMBackend:
    """Factory function to create LLM backend."""
    provider = provider.lower()

    if provider == "llamacpp":
        return LlamaCppBackend(model_path=model, **kwargs)
    elif provider == "ollama":
        return OllamaBackend(model=model, **kwargs)
    elif provider in ("openrouter", "openai", "vllm", "lmstudio"):
        return OpenAICompatibleBackend(model=model, **kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider}")