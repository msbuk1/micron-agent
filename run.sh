#!/usr/bin/env bash
# Convenience launcher for micron — uses the project venv's Python3.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --dev: run under `textual run --dev` so the devtools console shows every
# MarkupError (Textual truncates to "1 of 3 errors shown" otherwise).
# Requires `textual` in the venv (`pip install textual textual-dev` and
# `textual console` running in another terminal).
if [[ "${1:-}" == "--dev" ]]; then
  shift
  if ! "$SCRIPT_DIR/.venv/bin/python3" -c "import textual" 2>/dev/null; then
    echo "run.sh --dev: textual not installed in .venv — run: .venv/bin/pip install textual textual-dev" >&2
    echo "Falling back to normal run (errors will be truncated to 1/3)." >&2
    exec "$SCRIPT_DIR/.venv/bin/python3" -m micron "$@"
  fi
  # textual run --dev expects a command string; -- separates textual opts from the app command
  exec "$SCRIPT_DIR/.venv/bin/python3" -m textual run --dev -- "$SCRIPT_DIR/.venv/bin/python3" -m micron "$@"
fi

exec "$SCRIPT_DIR/.venv/bin/python3" -m micron "$@"
