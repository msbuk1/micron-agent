"""Tests for backend factory chat_format handling."""
from micron.llm import LlamaCppBackend, create_backend


def test_chat_format_warned_and_dropped_for_server_provider(capsys):
    backend = create_backend(
        provider="lmstudio",
        model="ministral-3-14b",
        api_key="no_key",
        base_url="http://localhost:1234/v1",
        chat_format="gemmaml",
    )
    out, _ = capsys.readouterr()
    assert "Ignoring chat_format='gemmaml'" in out
    assert not hasattr(backend, "chat_format")
    assert "chat_format" not in backend.__dict__


def test_chat_format_passes_through_for_llamacpp(capsys):
    backend = create_backend(
        provider="llamacpp",
        model="models/mistral-7b.gguf",
        chat_format="mistral-instruct",
    )
    out, _ = capsys.readouterr()
    assert "Ignoring chat_format" not in out
    assert isinstance(backend, LlamaCppBackend)
    assert backend._init_kwargs["chat_format"] == "mistral-instruct"
