#!/usr/bin/env bash
# Fallback outbound notifier for agents with no native hook system (e.g. Codex).
# Polls a tmux pane. If the visible output hasn't changed for IDLE_SECS and
# the last line looks like a prompt, fires notify.sh treating it as "waiting
# for input." This is a heuristic, not exact -- tune PROMPT_REGEX for your
# tool's actual prompt style.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?usage: watch_pane.sh <tmux-session-name>}"
IDLE_SECS="${IDLE_SECS:-8}"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "watch_pane.sh: need python3 or python on PATH" >&2; exit 1; }
PROMPT_REGEX="${PROMPT_REGEX:-\\?\\s*$|\\(y/n\\)|approve|Continue\\?|Allow\\?}"

LAST_HASH=""
STABLE_SINCE=$(date +%s)
NOTIFIED=0

echo "watching tmux session '$SESSION' (idle=${IDLE_SECS}s)..."

while true; do
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "session '$SESSION' is gone, stopping."
    exit 0
  fi

  PANE=$(tmux capture-pane -t "$SESSION" -p | tail -n 5)
  HASH=$(printf '%s' "$PANE" | md5sum | cut -d' ' -f1)
  NOW=$(date +%s)

  if [ "$HASH" != "$LAST_HASH" ]; then
    LAST_HASH="$HASH"
    STABLE_SINCE="$NOW"
    NOTIFIED=0
  fi

  if [ "$((NOW - STABLE_SINCE))" -ge "$IDLE_SECS" ] && [ "$NOTIFIED" -eq 0 ]; then
    if printf '%s' "$PANE" | grep -Eiq "$PROMPT_REGEX"; then
      LAST_LINE=$(printf '%s' "$PANE" | tail -n 1)
      JSON_MSG=$("$PY" -c "import json,sys; print(json.dumps(sys.argv[1]))" "$LAST_LINE")
      echo "{\"message\": $JSON_MSG}" \
        | TMUX_SESSION_NAME="$SESSION" "$SCRIPT_DIR/../hooks/notify.sh" input
      NOTIFIED=1
    fi
  fi

  sleep 2
done
