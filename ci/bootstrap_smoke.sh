#!/usr/bin/env bash
# Run scripts/bootstrap.sh end to end in a throwaway container.
#
# Until this existed the Linux install path had never actually been run -- it
# was only ever exercised indirectly, through the Windows installer calling it
# inside WSL. Every assertion below is something a person following the README
# would hit within their first minute.
#
#   AB_SMOKE_REAL_CLAUDE=1   download the real Claude Code installer instead of
#                            stubbing it (used by the weekly scheduled run, so
#                            upstream changing that installer shows up here)
set -uo pipefail

FAILED=0
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
head_() { printf '\n==> %s\n' "$*"; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# This script deletes .env and rewrites ~/.claude, ~/.bashrc and ~/.venvs. That
# is fine in a throwaway container and ruinous on a working machine, so refuse
# to run anywhere else unless somebody is very deliberate about it.
if [ -z "${CI:-}" ] && [ "${AB_SMOKE_FORCE:-0}" != "1" ]; then
  echo "bootstrap_smoke.sh is destructive and only runs in CI." >&2
  echo "It removes $REPO/.env and overwrites files in \$HOME." >&2
  echo "If you really mean it in a container: AB_SMOKE_FORCE=1 $0" >&2
  exit 2
fi

head_ "Container prerequisites"
# bootstrap.sh calls sudo, which a root container does not ship. Standing in a
# shim is closer to a real machine than editing the script for CI would be.
if ! command -v sudo >/dev/null; then
  # Real sudo applies a leading NAME=VALUE as an assignment; a bare `exec "$@"`
  # instead tries to run a program called DEBIAN_FRONTEND=noninteractive, so
  # every apt call in bootstrap.sh failed. `env` handles the assignment.
  printf '#!/bin/sh\nexec env "$@"\n' > /usr/local/bin/sudo
  chmod +x /usr/local/bin/sudo
  pass "installed a sudo shim (already root)"
else
  pass "sudo present"
fi

if [ "${AB_SMOKE_REAL_CLAUDE:-0}" = "1" ]; then
  pass "will download the real Claude Code installer"
else
  # bootstrap.sh skips the download when claude is already present, so a stub
  # keeps the run offline and fast without branching the script under test.
  mkdir -p "$HOME/.local/bin"
  # Real sudo applies a leading NAME=VALUE as an assignment; a bare `exec "$@"`
  # instead tries to run a program called DEBIAN_FRONTEND=noninteractive, so
  # every apt call in bootstrap.sh failed. `env` handles the assignment.
  printf '#!/bin/sh\necho "0.0.0-stub (Claude Code)"\n' > "$HOME/.local/bin/claude"
  chmod +x "$HOME/.local/bin/claude"
  pass "stubbed claude (set AB_SMOKE_REAL_CLAUDE=1 to use the real installer)"
fi

# A fresh clone has no .env; bootstrap.sh is expected to create one from the
# example and then decline to start the bot, because the values are placeholders.
rm -f "$REPO/.env"

head_ "Running bootstrap.sh"
if bash "$REPO/scripts/bootstrap.sh"; then
  pass "bootstrap.sh exited 0"
else
  fail "bootstrap.sh exited $? -- see the output above"
fi

head_ "What a new user should now have"

[ -x "$HOME/.venvs/agent-bridge/bin/python" ] \
  && pass "virtualenv created" || fail "no virtualenv at ~/.venvs/agent-bridge"

if "$HOME/.venvs/agent-bridge/bin/python" -c 'import discord, dotenv' 2>/dev/null; then
  pass "discord.py and python-dotenv importable"
else
  fail "the venv cannot import discord / dotenv"
fi

SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  python3 - "$SETTINGS" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
cmds = [h.get("command", "")
        for entries in (s.get("hooks") or {}).values()
        for e in entries for h in e.get("hooks", [])]
missing = [n for n in ("notify.sh", "ask_options.sh")
           if not any(n in c for c in cmds)]
if missing:
    sys.exit(f"settings.json is missing hooks for: {', '.join(missing)}")
if any("__AGENT_BRIDGE_DIR__" in c for c in cmds):
    sys.exit("settings.json still contains the __AGENT_BRIDGE_DIR__ placeholder")
PY
  # shellcheck disable=SC2181
  if [ $? -eq 0 ]; then pass "hooks wired with real paths"; else fail "hook wiring is wrong"; fi
else
  fail "no ~/.claude/settings.json was written"
fi

[ -f "$REPO/.env" ] && pass ".env created from the example" || fail ".env was not created"
grep -q 'your-bot-token' "$REPO/.env" 2>/dev/null \
  && pass "bot correctly not started with placeholder credentials" \
  || fail ".env does not look like the untouched example"

[ -x "$HOME/.agent-bridge/bin/claude" ] \
  && pass "wrapper installed" || fail "no wrapper at ~/.agent-bridge/bin/claude"

# The wrapper only works if it wins the PATH race in a *fresh login shell*.
# It once lost, silently, because .profile sources .bashrc and then prepends
# ~/.local/bin afterwards -- so the real claude shadowed the wrapper again.
head_ "The wrapper wins in a fresh login shell"
RESOLVED="$(bash -lc 'command -v claude' 2>/dev/null)"
case "$RESOLVED" in
  *"/.agent-bridge/bin/claude") pass "login shell resolves claude to the wrapper" ;;
  "")                           fail "a login shell cannot find claude at all" ;;
  *)                            fail "a login shell resolves claude to $RESOLVED, not the wrapper" ;;
esac

head_ "Re-running is safe"
if bash "$REPO/scripts/bootstrap.sh" >/tmp/second-run.log 2>&1; then
  pass "second run exited 0"
else
  fail "second run exited non-zero"
  tail -20 /tmp/second-run.log
fi
HOOK_COUNT="$(grep -c 'notify.sh' "$SETTINGS" 2>/dev/null || echo 0)"
[ "$HOOK_COUNT" -le 2 ] \
  && pass "hooks did not stack up on re-run ($HOOK_COUNT notify.sh entries)" \
  || fail "hooks duplicated on re-run ($HOOK_COUNT notify.sh entries)"

printf '\n'
[ "$FAILED" -eq 0 ] && { echo "bootstrap smoke: passed"; exit 0; }
echo "bootstrap smoke: failed"
exit 1
