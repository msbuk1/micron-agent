"""Slice 5 (Tasks 13+15): _HistoryCompactor token-budget trigger (red) + short-history lock (green)."""

import pytest

from micron.agent import _HistoryCompactor


def test_compress_triggers_on_tokens_not_count():
    """3 short-count messages but over token budget must compress (RED: max_tokens not implemented)."""
    compactor = _HistoryCompactor(keep_recent=8, max_tokens=2000)
    history = [
        {"role": "user", "content": "x" * 5000},
        {"role": "assistant", "content": "y" * 5000},
        {"role": "user", "content": "hello"},
    ]
    assert compactor.should_compress(history) is True
    compressed = compactor.compress(history)
    assert compressed[0]["content"].startswith("Previous conversation")


def test_short_history_untouched():
    """Single short message passes through unchanged (locks existing behavior)."""
    compactor = _HistoryCompactor(keep_recent=8)
    history = [{"role": "user", "content": "hello"}]
    assert compactor.should_compress(history) is False
    assert compactor.compress(history) == history
