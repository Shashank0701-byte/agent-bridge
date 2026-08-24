#!/usr/bin/env bash
# Fallback outbound notifier for agents with no native hook system (e.g. Codex).
#
# Polls a tmux pane. Once the visible output has been unchanged for IDLE_SECS
# and a recent line looks like a prompt, fires notify.sh treating it as "waiting
# for input". This is a heuristic, not exact -- tune PROMPT_REGEX for your tool.
#
# Usage: watch_pane.sh <tmux-session-name>
#        IDLE_SECS=5 PROMPT_REGEX='\(y/n\)|continue\?' ./watch_pane.sh mysession
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?usage: watch_pane.sh <tmux-session-name>}"
IDLE_SECS="${IDLE_SECS:-8}"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "watch_pane.sh: need python3 or python on PATH" >&2; exit 1; }
PROMPT_REGEX="${PROMPT_REGEX:-\?\s*$|\(y/n\)|approve|Continue\?|Allow\?}"

# capture-pane returns the FULL pane height, and a pane is mostly trailing blank
# lines because output sits at the top. Tailing the raw capture therefore only
# ever sees blanks and nothing matches -- so drop blank lines before tailing.
recent_lines() {
  tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -v '^[[:space:]]*$' | tail -n 5
}

LAST_HASH=""
STABLE_SINCE=$(date +%s)
NOTIFIED=0

echo "watching tmux session '$SESSION' (idle=${IDLE_SECS}s)..."

while true; do
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "session '$SESSION' is gone, stopping."
    exit 0
  fi

  PANE="$(recent_lines)"
  HASH=$(printf '%s\n' "$PANE" | md5sum | cut -d' ' -f1)
  NOW=$(date +%s)

  if [ "$HASH" != "$LAST_HASH" ]; then
    LAST_HASH="$HASH"
    STABLE_SINCE="$NOW"
    NOTIFIED=0
  fi

  if [ "$((NOW - STABLE_SINCE))" -ge "$IDLE_SECS" ] && [ "$NOTIFIED" -eq 0 ]; then
    # Report the line that actually matched, not simply the last line -- the
    # prompt is often followed by an input indicator or a blank input row.
    MATCH_LINE="$(printf '%s\n' "$PANE" | grep -Ei "$PROMPT_REGEX" | tail -n 1 || true)"
    if [ -n "$MATCH_LINE" ]; then
      JSON_MSG=$("$PY" -c "import json,sys; print(json.dumps(sys.argv[1].strip()))" "$MATCH_LINE")
      printf '{"message": %s}\n' "$JSON_MSG" \
        | TMUX_SESSION_NAME="$SESSION" "$SCRIPT_DIR/../hooks/notify.sh" input
      NOTIFIED=1
    fi
  fi

  sleep 2
done
