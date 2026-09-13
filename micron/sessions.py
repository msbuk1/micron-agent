"""Session persistence — the append-only log is the source of truth.

The session file is an append-only JSONL log. Model-visible history is
*projected* from it (:meth:`SessionLogger.derive_messages`), never
reconstructed from a side-channel history list. Two entry kinds:

- ``message`` — settled, model-visible content (user / assistant / tool).
  Committed once; never rewritten in place.
- ``attempt`` — log-only record of a failed / retried / cancelled stream.
  Replayable and UI-visible, but never enters model history.

Format versioning: the session header carries ``format_version``. Version 1
files (no version field, ``turn`` entries) are migrated forward-only at
read time — ``turn`` entries project as ``message`` entries. Committed
generations are never rewritten in place.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

FORMAT_VERSION = 2  # v1: legacy "turn" entries, no version field


class SessionLogger:
    """Logs conversation turns to disk as JSONL files."""

    def __init__(
        self,
        sessions_dir: str | Path,
        max_session_bytes: int = 5 * 1024 * 1024,  # 5MB per session
        max_sessions: int = 100,  # Keep last N sessions
    ):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.max_session_bytes = max_session_bytes
        self.max_sessions = max_sessions
        self._current_file: Optional[Path] = None
        self._session_id: Optional[str] = None

    def start_session(self) -> str:
        """Start a new session file. Returns the session ID."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self._session_id = timestamp
        self._current_file = self.sessions_dir / f"{timestamp}.jsonl"

        # Write session header
        header = {
            "type": "session_start",
            "id": timestamp,
            "timestamp": datetime.now().isoformat(),
            "hostname": os.uname().nodename,
            "format_version": FORMAT_VERSION,
        }
        self._append(header)
        self._cleanup()
        return timestamp

    @property
    def session_id(self) -> Optional[str]:
        """ID of the current session (None before start_session)."""
        return self._session_id

    def log_turn(self, role: str, content: str, tool_calls: list = None):
        """Log a single conversation turn (legacy audit-trail entry).

        New code should use :meth:`log_message` (model-visible, settled) or
        :meth:`log_attempt` (log-only failed stream) instead.
        """
        if not self._current_file:
            return

        entry = {
            "type": "turn",
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls

        self._append_checked(entry)

    def log_message(
        self,
        role: str,
        content: str,
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ):
        """Commit settled, model-visible content as a ``message`` entry.

        This is the only way new model-visible input enters the log — the
        projection (:meth:`derive_messages`) reads exactly these entries.
        """
        if not self._current_file:
            return
        entry = {
            "type": "message",
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls
        if tool_call_id is not None:
            entry["tool_call_id"] = tool_call_id
        if name is not None:
            entry["name"] = name
        self._append_checked(entry)

    def log_attempt(self, role: str, content: str, reason: str):
        """Record a failed/retried/cancelled stream as a log-only ``attempt``.

        Attempts are replayable and UI-visible (see :meth:`read_entries`)
        but never enter model history — :meth:`derive_messages` skips them.
        """
        if not self._current_file:
            return
        self._append_checked({
            "type": "attempt",
            "role": role,
            "content": content,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        })

    def _append_checked(self, entry: dict):
        """Append with the per-session size rollover check."""
        if self._current_file.exists() and self._current_file.stat().st_size >= self.max_session_bytes:
            self.start_session()  # Start a new session file
        self._append(entry)

    def end_session(self):
        """Mark the session as ended."""
        if self._current_file:
            self._append({"type": "session_end", "timestamp": datetime.now().isoformat()})

    def list_sessions(self, n: int = 20) -> list[dict]:
        """List recent sessions with summary info."""
        sessions = []
        for f in sorted(self.sessions_dir.glob("*.jsonl"), reverse=True)[:n]:
            try:
                info = self._read_header(f)
                info["file"] = f.name
                info["size"] = f.stat().st_size
                info["turns"] = self._count_turns(f)
                sessions.append(info)
            except Exception:
                continue
        return sessions

    def read_entries(self, session_id: str) -> list[dict]:
        """Read every log entry (messages, attempts, lifecycle) in order."""
        f = self.sessions_dir / f"{session_id}.jsonl"
        if not f.exists():
            return []

        entries = []
        for line in f.read_text().strip().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def format_version(self, session_id: str) -> int:
        """Return the stored format version (1 for legacy headers)."""
        f = self.sessions_dir / f"{session_id}.jsonl"
        if not f.exists():
            return FORMAT_VERSION
        try:
            return int(self._read_header(f).get("format_version", 1))
        except Exception:
            return 1

    def read_session(self, session_id: str) -> list[dict]:
        """Read model-visible entries from a session (transcript view).

        Returns ``message`` entries — plus, as the forward-only adjacent
        migration step, legacy v1 ``turn`` entries projected as messages.
        ``attempt`` entries are excluded; use :meth:`read_entries` for the
        full log including attempts. Files are never rewritten in place.
        """
        return [
            e for e in self._project_entries(self.read_entries(session_id))
        ]

    def derive_messages(
        self, session_id: str | None = None, max_messages: int | None = 20,
    ) -> list[dict]:
        """Project the log into the message list the model sees.

        The single seam every consumer (resume, fork, transcript, the
        agent's own request builder) must read history through. Attempts
        never appear here. ``max_messages`` windows the projection; the
        log itself stays lossless.
        """
        sid = session_id or self._session_id
        if not sid:
            return []
        msgs = self._project_entries(self.read_entries(sid))
        if max_messages is not None:
            msgs = msgs[-max_messages:]
        return msgs

    @staticmethod
    def _project_entries(entries: list[dict]) -> list[dict]:
        """Forward-only adjacent migration: project log entries to messages.

        v2 ``message`` entries pass through; v1 ``turn`` entries project as
        messages (read-time only — committed generations are never
        rewritten in place). Everything else (attempts, lifecycle) is
        dropped.
        """
        msgs = []
        for e in entries:
            t = e.get("type")
            if t not in ("message", "turn"):
                continue
            m = {"role": e.get("role", "user"), "content": e.get("content", "")}
            if e.get("tool_calls"):
                m["tool_calls"] = e["tool_calls"]
            if e.get("tool_call_id") is not None:
                m["tool_call_id"] = e["tool_call_id"]
            if e.get("name") is not None:
                m["name"] = e["name"]
            msgs.append(m)
        return msgs

    def get_session_context(self, session_id: str, max_turns: int = 20) -> list[dict]:
        """Get a session's history formatted for the agent's history parameter.

        Thin alias over :meth:`derive_messages` — the log is the authority.
        """
        return self.derive_messages(session_id, max_messages=max_turns)

    def _append(self, entry: dict):
        """Append a JSON line to the current session file."""
        with open(self._current_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _read_header(self, path: Path) -> dict:
        """Read the first line (session header) from a file."""
        with open(path) as f:
            return json.loads(f.readline())

    def _count_turns(self, path: Path) -> int:
        """Count turn entries in a session file."""
        count = 0
        for line in path.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("type") == "turn":
                    count += 1
            except json.JSONDecodeError:
                continue
        return count

    def _cleanup(self):
        """Remove old sessions beyond the max limit."""
        files = sorted(self.sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        if len(files) > self.max_sessions:
            for f in files[: len(files) - self.max_sessions]:
                f.unlink()
