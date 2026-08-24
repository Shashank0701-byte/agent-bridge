#!/usr/bin/env bash
# Starts a named tmux session running your coding agent, in a project directory.
#
# Usage: start_session.sh [project-dir] [command]
#   cd ~/code/portfolio && ./start_session.sh     # session "portfolio", runs claude
#   ./start_session.sh ~/code/portfolio           # same, from anywhere
#   ./start_session.sh ~/code/api codex           # runs codex instead of claude
#   SESSION_NAME=api-v2 ./start_session.sh ~/code/api   # override the derived name
#
# The session name is what Discord messages are labelled with and what
# `!name your reply` targets, so it is derived from the folder name.
set -euo pipefail

DIR="${1:-$PWD}"
CMD="${2:-claude}"

[ -d "$DIR" ] || { echo "no such directory: $DIR" >&2; exit 1; }
DIR="$(cd "$DIR" && pwd)"   # normalise to an absolute path

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
echo "  running  : $CMD"
echo "  attach   : tmux attach -t $NAME   (detach: Ctrl-b then d)"
echo "  discord  : replies land here automatically; or target it with '!$NAME your reply'"
