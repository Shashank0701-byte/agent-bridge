# shellcheck shell=bash
# Shared: derive a tmux session name from a directory path.
#
# Both start_session.sh and the `claude` wrapper need this to agree exactly --
# if they ever disagree, the same folder ends up with two different sessions and
# Discord replies go to the wrong one.
#
# tmux splits target names on "." and ":", so those cannot appear in a session
# name; anything else outside [A-Za-z0-9_-] is dropped.
agent_bridge_session_name() {
  local dir="$1" name
  name="${SESSION_NAME:-$(basename "$dir")}"
  name="$(printf '%s' "$name" | tr '.:' '--' | tr -cd '[:alnum:]_-')"
  printf '%s' "$name"
}
