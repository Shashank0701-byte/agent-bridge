#!/usr/bin/env bash
# Thin shim around ask_options.py -- see notify.sh for why the logic is Python.
#
# Deliberately NON-BLOCKING: PreToolUse runs *before* the tool, so blocking here
# would stop the question card rendering and lock you out of answering at your
# own keyboard. It notifies and exits 0 whatever happens.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || exit 0          # never break the session over a notifier

"$PY" "$SCRIPT_DIR/ask_options.py" || true
exit 0
