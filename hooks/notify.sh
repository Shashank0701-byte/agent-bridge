#!/usr/bin/env bash
# Thin shim around notify.py.
#
# The logic moved to Python so the same hook works on native Windows, where
# `bash` on PATH is the WSL shim -- a .sh hook there runs in a different
# operating system from the agent that fired it. This file stays so that a
# settings.json written by an older install keeps working after an update.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "notify.sh: need python3 or python on PATH" >&2; exit 1; }

exec "$PY" "$SCRIPT_DIR/notify.py" "$@"
