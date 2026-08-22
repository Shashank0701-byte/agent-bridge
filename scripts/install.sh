#!/usr/bin/env bash
# One-time setup: wires the Notification/Stop hooks into Claude Code's
# settings.json and makes the scripts executable.
#
# The merge is done in Python rather than jq -- one less thing to install, and
# jq's `*` operator replaces arrays wholesale, which would have silently thrown
# away any hooks you already had configured for the same events.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "install.sh: need python3 or python on PATH" >&2; exit 1; }

mkdir -p "$HOME/.claude"

if [ -f "$CLAUDE_SETTINGS" ]; then
  BACKUP="$CLAUDE_SETTINGS.bak-$(date +%Y%m%d%H%M%S)"
  cp "$CLAUDE_SETTINGS" "$BACKUP"
  echo "backed up existing settings to $BACKUP"
fi

"$PY" - "$CLAUDE_SETTINGS" "$REPO_DIR/config/claude-settings.snippet.json" "$REPO_DIR" <<'PY_MERGE'
import json, os, sys

settings_path, snippet_path, repo_dir = sys.argv[1], sys.argv[2], sys.argv[3]

raw = open(snippet_path).read().replace("__AGENT_BRIDGE_DIR__", repo_dir)
new = json.loads(raw)

current = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            text = f.read().strip()
        current = json.loads(text) if text else {}
    except json.JSONDecodeError as e:
        sys.exit(f"install.sh: {settings_path} is not valid JSON ({e}); fix it and re-run")


def ours(entry):
    """An agent-bridge hook entry, from this install or an earlier one."""
    return any("notify.sh" in (h.get("command") or "")
               for h in entry.get("hooks", []))


hooks = current.get("hooks") or {}
for event, entries in (new.get("hooks") or {}).items():
    # Drop our previous entries before re-adding, so re-running install.sh (or
    # moving the repo) updates the path instead of stacking up duplicates.
    kept = [e for e in (hooks.get(event) or []) if not ours(e)]
    hooks[event] = kept + entries
    if kept:
        print(f"  {event}: kept {len(kept)} existing hook(s), added ours")
    else:
        print(f"  {event}: added")
current["hooks"] = hooks

for key, value in new.items():
    if key != "hooks":
        current[key] = value

tmp = settings_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(current, f, indent=2)
    f.write("\n")
os.replace(tmp, settings_path)
print(f"wrote {settings_path}")
PY_MERGE

chmod +x "$REPO_DIR/hooks/notify.sh" "$REPO_DIR/poller/watch_pane.sh" \
         "$REPO_DIR/scripts/start_session.sh" "$REPO_DIR/scripts/install.sh"

echo ""
echo "Done. Remaining steps:"
echo "  1. cp .env.example .env   # then fill in DISCORD_BOT_TOKEN and DISCORD_USER_ID"
echo "  2. pip install -r requirements.txt"
echo "  3. python3 bot/bot.py     # run this as a persistent process (systemd/pm2)"
echo "  4. ./scripts/start_session.sh myproject   # launches a tmux session running claude"
