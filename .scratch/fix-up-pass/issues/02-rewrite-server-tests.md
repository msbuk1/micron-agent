# 02 — Rewrite Server Tests with httpx.AsyncClient

**What to build:** Replace the threading-skip approach in `test_server.py` with proper `httpx.AsyncClient` async tests. Server tests should actually run and pass, not silently skip.

**Blocked by:** None — can start immediately.

**Status:** ✅ done — verified in code (2026-08-03); 11 server tests pass, 0 skips

- [x] Server tests use `httpx.AsyncClient` with async fixtures
- [x] No silent `pytest.skip` — if threading fails, use `pytest.mark.skipif` with a clear reason
- [x] All server tests pass (or skip with explicit reason, not silently)
- [x] Test count in docs reflects actual passing tests
