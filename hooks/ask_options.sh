#!/usr/bin/env bash
# PreToolUse hook for AskUserQuestion.
#
# Claude Code passes the full question structure (questions, options, labels,
# descriptions, multiSelect) in tool_input, so the choices can be shown in
# Discord rather than only on screen.
#
# Deliberately NON-BLOCKING: PreToolUse runs *before* the tool, so blocking here
# would stop the question card from rendering and lock you out of answering at
# your own keyboard. It notifies and exits 0; bot.py handles the reply.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/../.env" ] && set -a && source "$SCRIPT_DIR/../.env" && set +a
export DISCORD_BOT_TOKEN DISCORD_USER_ID

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || exit 0          # never break the session over a notifier

STATE_FILE="${AGENT_BRIDGE_STATE:-$HOME/.agent-bridge/state.json}"
STATE_FILE="${STATE_FILE/#\~/$HOME}"
STATE_DIR="$(dirname "$STATE_FILE")"
SESSION_NAME="${TMUX_SESSION_NAME:-$(tmux display-message -p '#S' 2>/dev/null || echo unknown)}"

PAYLOAD="$(cat || true)"

printf '%s' "$PAYLOAD" | AB_SESSION="$SESSION_NAME" AB_STATE_DIR="$STATE_DIR" \
  "$PY" "$SCRIPT_DIR/ask_options.py" || true

exit 0    # a failed notification must never block the agent
