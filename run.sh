#!/usr/bin/env bash
# Convenience launcher for micron — uses the project venv's Python3.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/python3" -m micron "$@"
