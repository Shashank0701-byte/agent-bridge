#!/usr/bin/env bash
# Control the long-running Discord bot.
#
#   bot_ctl.sh start | stop | restart | status | logs | supervise
#
# `supervise` is the entry point used by autostart: it runs the bot in a loop
# so a crash or a dropped connection that kills the process comes back on its
# own. Run it in the foreground; it never returns.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$HOME/.venvs/agent-bridge/bin/python"
LOG="${AGENT_BRIDGE_LOG:-$HOME/.agent-bridge/bot.log}"
PIDFILE="$HOME/.agent-bridge/bot.pid"
mkdir -p "$(dirname "$LOG")"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }

case "${1:-status}" in
  supervise)
    echo "$$" > "$PIDFILE"
    trap 'rm -f "$PIDFILE"' EXIT
    cd "$REPO"
    while true; do
      echo "[$(date '+%F %T')] starting bot" >> "$LOG"
      "$VENV" bot/bot.py >> "$LOG" 2>&1
      echo "[$(date '+%F %T')] bot exited (code $?), restarting in 5s" >> "$LOG"
      sleep 5
    done
    ;;

  start)
    if running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    [ -x "$VENV" ] || { echo "venv missing: $VENV" >&2; exit 1; }
    # setsid puts the supervisor in its OWN process group. Without it, a
    # non-interactive shell shares its process group with background jobs, and
    # `stop` (which kills the group) would take its own caller down with it.
    setsid nohup "$REPO/scripts/bot_ctl.sh" supervise >/dev/null 2>&1 &
    # Poll rather than sleep a fixed time: launching from a /mnt drive is slow.
    for _ in $(seq 1 30); do running && break; sleep 1; done
    running && echo "started (pid $(cat "$PIDFILE"))" || { echo "failed to start; see $LOG" >&2; exit 1; }
    ;;

  stop)
    if ! running; then echo "not running"; exit 0; fi
    pid="$(cat "$PIDFILE")"
    # Kill the supervisor's process group so the python child dies with it.
    kill -- -"$(ps -o pgid= "$pid" | tr -d ' ')" 2>/dev/null || kill "$pid" 2>/dev/null
    sleep 1
    rm -f "$PIDFILE"
    echo "stopped"
    ;;

  restart) "$0" stop; "$0" start ;;

  status)
    if running; then
      echo "running (pid $(cat "$PIDFILE"))"
      grep -v 'PyNaCl\|davey' "$LOG" 2>/dev/null | tail -3
    else
      echo "not running"
    fi
    echo "log: $LOG"
    ;;

  logs) tail -f "$LOG" ;;

  *) echo "usage: bot_ctl.sh start|stop|restart|status|logs|supervise" >&2; exit 2 ;;
esac
