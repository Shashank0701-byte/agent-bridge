#!/usr/bin/env bash
# Starts a named tmux session running your coding agent, in a project directory.
#
# Usage: start_session.sh [project-dir] [agent or command]
#   cd ~/code/portfolio && ./start_session.sh     # session "portfolio", runs claude
#   ./start_session.sh ~/code/portfolio           # same, from anywhere
#   ./start_session.sh ~/code/api cursor          # Cursor CLI (`agent`) plus a prompt poller
#   ./start_session.sh ~/code/api codex           # codex, watched for a prompt
#   ./start_session.sh ~/code/api gemini          # gemini, watched for a prompt
#   ./start_session.sh ~/code/api "codex --full-auto"
#   SESSION_NAME=api-v2 ./start_session.sh ~/code/api   # override the derived name
#
# Known names are resolved by hooks/lib/agents.py. Anything else is the command
# itself, and is not polled. AGENT_BRIDGE_POLL=0 skips the poller.
#
# The session name is what Discord messages are labelled with and what
# `!name your reply` targets, so it is derived from the folder name.
set -euo pipefail

DIR="${1:-$PWD}"
REQUESTED="${2:-claude}"

[ -d "$DIR" ] || { echo "no such directory: $DIR" >&2; exit 1; }
DIR="$(cd "$DIR" && pwd)"   # normalise to an absolute path

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "start_session.sh: need python3 or python on PATH" >&2; exit 1; }
RESOLVED="$("$PY" - "$REPO_DIR/hooks/lib" "$REQUESTED" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from agents import resolve
print(json.dumps(resolve(sys.argv[2])))
PY
)"
CMD="$(printf '%s' "$RESOLVED" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["command"])')"
PROMPT_REGEX="$(printf '%s' "$RESOLVED" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["prompt_regex"] or "")')"
AGENT_ID="$(printf '%s' "$RESOLVED" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["id"] or "")')"

. "$(dirname "${BASH_SOURCE[0]}")/lib/session_name.sh"
NAME="$(agent_bridge_session_name "$DIR")"
[ -n "$NAME" ] || { echo "could not derive a session name from $DIR" >&2; exit 1; }

if tmux has-session -t "$NAME" 2>/dev/null; then
  echo "session '$NAME' already exists. Attach with: tmux attach -t $NAME"
  exit 0
fi

tmux new -d -s "$NAME" -c "$DIR"
tmux send-keys -t "$NAME" "$CMD" Enter

echo "started tmux session '$NAME'"
echo "  directory: $DIR"
echo "  agent    : ${AGENT_ID:-custom}"
echo "  running  : $CMD"
echo "  attach   : tmux attach -t $NAME   (detach: Ctrl-b then d)"
echo "  discord  : replies land here automatically; or target it with '!$NAME your reply'"

# Claude notifies through its own hooks. Cursor's IDE notifies through
# hooks.json. A terminal agent has neither, so watch the pane. Cursor's CLI
# is watched too: its y/n prompt is on screen, and the IDE hook does not run
# inside this tmux session unless Cursor itself is the process.
if [ -n "$PROMPT_REGEX" ] && [ "${AGENT_BRIDGE_POLL:-1}" != "0" ]; then
  mkdir -p "$HOME/.agent-bridge"
  LOG="$HOME/.agent-bridge/poller-$NAME.log"
  PROMPT_REGEX="$PROMPT_REGEX" "$REPO_DIR/poller/watch_pane.sh" "$NAME" >>"$LOG" 2>&1 &
  echo "  poller   : pid $! (log: $LOG)"
fi
if [ "$AGENT_ID" = "cursor" ]; then
  echo "  ide      : python \"$REPO_DIR/scripts/install_cursor.py\"  # DMs when the IDE wants to run a command"
fi
