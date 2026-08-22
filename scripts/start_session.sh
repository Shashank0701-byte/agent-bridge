#!/usr/bin/env bash
# Starts a named tmux session running your coding agent.
# Usage: start_session.sh <session-name> [command]
#   ./start_session.sh myproject            # runs `claude`
#   ./start_session.sh myproject codex      # runs `codex`
set -euo pipefail

NAME="${1:?usage: start_session.sh <session-name> [command]}"
CMD="${2:-claude}"

if tmux has-session -t "$NAME" 2>/dev/null; then
  echo "session '$NAME' already exists. Attach with: tmux attach -t $NAME"
  exit 0
fi

tmux new -d -s "$NAME"
tmux send-keys -t "$NAME" "$CMD" Enter
echo "started tmux session '$NAME' running: $CMD"
echo "attach with: tmux attach -t $NAME"
echo "detach with: Ctrl-b then d"
