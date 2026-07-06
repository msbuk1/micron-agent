"""Session persistence — saves conversation history to disk."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


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
        }
        self._append(header)
        self._cleanup()
        return timestamp

    def log_turn(self, role: str, content: str, tool_calls: list = None):
        """Log a single conversation turn."""
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

        # Check file size before writing
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

    def read_session(self, session_id: str) -> list[dict]:
        """Read all turns from a session."""
        f = self.sessions_dir / f"{session_id}.jsonl"
        if not f.exists():
            return []

        turns = []
        for line in f.read_text().strip().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("type") == "turn":
                    turns.append(entry)
            except json.JSONDecodeError:
                continue
        return turns

    def get_session_context(self, session_id: str, max_turns: int = 20) -> list[dict]:
        """Get a session's history formatted for the agent's history parameter."""
        turns = self.read_session(session_id)
        messages = []
        for turn in turns[-max_turns:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        return messages

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
