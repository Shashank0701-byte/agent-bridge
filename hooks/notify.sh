#!/usr/bin/env bash
# Outbound leg of the bridge.
# Called by Claude Code's Notification/Stop hooks (or by poller/watch_pane.sh
# for agents without native hooks). Reads hook JSON from stdin, sends you a
# Discord DM, and records which tmux session pinged last so replies can
# auto-target it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/../.env" ] && set -a && source "$SCRIPT_DIR/../.env" && set +a

: "${DISCORD_BOT_TOKEN:?Set DISCORD_BOT_TOKEN in .env}"
: "${DISCORD_USER_ID:?Set DISCORD_USER_ID in .env}"
export DISCORD_BOT_TOKEN DISCORD_USER_ID

# Debian-ish systems call it python3; conda and Windows often only ship `python`.
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "notify.sh: need python3 or python on PATH" >&2; exit 1; }

STATE_FILE="${AGENT_BRIDGE_STATE:-$HOME/.agent-bridge/state.json}"
STATE_FILE="${STATE_FILE/#\~/$HOME}"
mkdir -p "$(dirname "$STATE_FILE")"

# Which tmux session is this? Prefer an explicit env var (poller sets this),
# fall back to asking tmux directly (works when the hook fires inside the session).
SESSION_NAME="${TMUX_SESSION_NAME:-$(tmux display-message -p '#S' 2>/dev/null || echo unknown)}"
KIND="${1:-input}"   # "input" -> Notification hook, "done" -> Stop hook

PAYLOAD="$(cat || true)"   # hook JSON on stdin; may be empty
MSG_TEXT=$(printf '%s' "$PAYLOAD" | "$PY" -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('message') or d.get('reason') or 'Agent needs your input')
except Exception:
    print('Agent needs your input')
" 2>/dev/null)

if [ "$KIND" = "done" ]; then
  TEXT="[$SESSION_NAME] Task finished."
else
  TEXT="[$SESSION_NAME] Needs input: $MSG_TEXT"
fi

# Remember last session that pinged (so a plain reply knows where to go).
"$PY" - "$STATE_FILE" "$SESSION_NAME" <<'PY_STATE'
import json, sys, os
state_file, session = sys.argv[1], sys.argv[2]
state = {}
if os.path.exists(state_file):
    try:
        state = json.load(open(state_file))
    except Exception:
        state = {}
state["last_session"] = session
json.dump(state, open(state_file, "w"))
PY_STATE

# Send the DM. Webhooks can only post to channels, never to a DM, so this goes
# through the bot REST API instead: open the DM channel, then post to it.
# Opening is idempotent -- Discord returns the existing channel if there is one.
"$PY" - "$KIND" "$TEXT" <<'PY_SEND'
import json, os, sys, urllib.error, urllib.request

API = "https://discord.com/api/v10"
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
kind, text = sys.argv[1], sys.argv[2]
text = ("✅ " if kind == "done" else "\U0001f7e1 ") + text


def post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (agent-bridge, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


try:
    channel = post(f"{API}/users/@me/channels",
                   {"recipient_id": str(os.environ["DISCORD_USER_ID"])})
    # 2000 characters is Discord's hard cap on message content.
    post(f"{API}/channels/{channel['id']}/messages", {"content": text[:2000]})
except urllib.error.HTTPError as e:
    detail = e.read().decode("utf-8", "replace")
    print(f"notify.sh: Discord API returned {e.code}: {detail}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"notify.sh: could not send DM: {e}", file=sys.stderr)
    sys.exit(1)
PY_SEND
