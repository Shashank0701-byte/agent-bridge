#!/usr/bin/env bash
# Transparent `claude` wrapper that turns the bridge on automatically.
#
# Installed earlier on PATH than the real binary (see install_wrapper.sh), so
# typing `claude` anywhere:
#   1. makes sure the Discord bot is running,
#   2. puts the session inside tmux named after the current folder,
#   3. runs the real claude.
#
# It deliberately gets out of the way for anything non-interactive.
set -uo pipefail

REPO="__AGENT_BRIDGE_DIR__"
REAL="__REAL_CLAUDE__"

[ -x "$REAL" ] || { echo "claude-wrapper: real binary missing at $REAL" >&2; exit 1; }

# --- pass straight through when wrapping would be wrong ------------------------
# Headless (-p/--print) and piped/scripted use: no tmux, no bot. Outbound DMs
# still work in these cases because notify.sh does not depend on the bot.
for arg in "$@"; do
  case "$arg" in
    -p|--print) exec "$REAL" "$@" ;;
  esac
done
[ -t 0 ] && [ -t 1 ] || exec "$REAL" "$@"

# Opt-out for one invocation: AGENT_BRIDGE_WRAP=0 claude
[ "${AGENT_BRIDGE_WRAP:-1}" = "1" ] || exec "$REAL" "$@"

# --- pick up where this folder left off ---------------------------------------
# The whole point of the bridge is walking away from a session and being pinged
# hours later, so `claude` in a project should rejoin that project's
# conversation. tmux -A below only rejoins a session that still exists; after a
# reboot or a WSL shutdown it does not, and the conversation would restart empty.
#
# --continue is safe to pass unconditionally: in a folder with no history it
# starts an ordinary fresh session rather than failing (checked against 2.1.241,
# both headless and interactive). It is also scoped to the current directory, so
# it can never pull in another project's conversation.
#
# For a deliberately fresh start: AGENT_BRIDGE_RESUME=0 claude
RESUME=""
if [ "${AGENT_BRIDGE_RESUME:-1}" = "1" ]; then
  RESUME="--continue"
  for arg in "$@"; do
    case "$arg" in
      # Already steering the conversation yourself: stay out of the way.
      -c|--continue|-r|--resume|--from-pr|--cloud|--bg|--background)
        RESUME=""; break ;;
    esac
  done
fi

# --- make sure replies have somewhere to land ---------------------------------
# Idempotent: a no-op costing one liveness check when the bot is already up.
"$REPO/scripts/bot_ctl.sh" start >/dev/null 2>&1 || true

# --- already inside tmux? then just run (also stops infinite recursion) --------
[ -n "${TMUX:-}" ] && exec "$REAL" ${RESUME:+"$RESUME"} "$@"

# --- otherwise wrap this folder in a tmux session ------------------------------
. "$REPO/scripts/lib/session_name.sh"
NAME="$(agent_bridge_session_name "$PWD")"
[ -n "$NAME" ] || exec "$REAL" "$@"   # unnameable dir: better to run than to fail

# -A attaches to an existing session for this folder instead of erroring, so
# re-running `claude` in a project rejoins the session you already had.
exec tmux new-session -A -s "$NAME" -c "$PWD" "$REAL" ${RESUME:+"$RESUME"} "$@"
