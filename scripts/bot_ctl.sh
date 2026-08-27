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
LOCKDIR="$HOME/.agent-bridge/supervisor.lock"
mkdir -p "$(dirname "$LOG")"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }

# Only one supervisor may exist, and `start`'s liveness check is not enough to
# guarantee that: the `claude` wrapper calls `start` on every invocation and the
# Windows logon task starts it too, so on boot both can pass the check in the
# same instant and each spawn one. Two bots on one token both receive every DM
# and both type the reply into tmux -- a doubled message, or on a prompt a digit
# that chooses and a second digit that lands somewhere else entirely.
#
# mkdir is the portable atomic test-and-set: it either creates the directory or
# fails, with no window in between. flock would be the obvious choice but macOS
# does not ship it.
acquire_lock() {
  for _ in 1 2; do
    if mkdir "$LOCKDIR" 2>/dev/null; then
      echo "$$" > "$LOCKDIR/pid"
      return 0
    fi
    holder="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      return 1                      # a live supervisor owns it
    fi
    # Left behind by a kill -9 or a reboot. Clear it only if it still names the
    # same dead process, so a lock someone else just took is never removed.
    still="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
    [ "$still" = "$holder" ] && rm -rf "$LOCKDIR"
  done
  return 1
}

release_lock() { [ "$(cat "$LOCKDIR/pid" 2>/dev/null || true)" = "$$" ] && rm -rf "$LOCKDIR"; }

# An orphaned supervisor must not delete the live one's pid file on its way out.
release_pidfile() { [ "$(cat "$PIDFILE" 2>/dev/null || true)" = "$$" ] && rm -f "$PIDFILE"; }

case "${1:-status}" in
  supervise)
    if ! acquire_lock; then
      echo "[$(date '+%F %T')] another supervisor already holds the lock; exiting" >> "$LOG"
      exit 0
    fi
    echo "$$" > "$PIDFILE"
    trap 'release_pidfile; release_lock' EXIT
    cd "$REPO" || exit 1
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
    # The supervisor's EXIT trap normally clears this, but it does not run on
    # SIGKILL. Removing a lock whose owner is gone is what keeps `stop; start`
    # working; a lock still owned by a live process is left strictly alone.
    holder="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
    if [ -z "$holder" ] || ! kill -0 "$holder" 2>/dev/null; then rm -rf "$LOCKDIR"; fi
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
