#!/usr/bin/env bash
# Run the one-command install the way a new person runs it: a bare container,
# nothing installed, then get.sh, which pipx-installs this checkout and runs
# agent-bridge setup. It must not leave a git clone in $HOME.
#
#   AB_CHECK_PUBLIC_URL  also assert the URL in the README still resolves; only
#                        meaningful once the commit is on the default branch
set -uo pipefail

FAILED=0
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
head_() { printf '\n==> %s\n' "$*"; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Install this checkout, not whatever main happens to be on the remote.
export AGENT_BRIDGE_REPO="$REPO"
export PIPX_HOME="${PIPX_HOME:-/opt/pipx}"
export PIPX_BIN_DIR="${PIPX_BIN_DIR:-/usr/local/bin}"

if [ -z "${CI:-}" ] && [ "${AB_SMOKE_FORCE:-0}" != "1" ]; then
  echo "install_smoke.sh installs into the home directory and rewrites it; CI only." >&2
  echo "In a container you really meant it: AB_SMOKE_FORCE=1 $0" >&2
  exit 2
fi

head_ "A bare container has none of this"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq git curl ca-certificates python3 python3-venv python3-pip >/dev/null 2>&1
python3 -m pip install -q pipx \
  && pass "pipx installed" || fail "could not install pipx"

if ! command -v sudo >/dev/null; then
  printf '#!/bin/sh\nexec env "$@"\n' > /usr/local/bin/sudo
  chmod +x /usr/local/bin/sudo
  pass "sudo shim (already root)"
fi
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\necho "0.0.0-stub (Claude Code)"\n' > "$HOME/.local/bin/claude"
chmod +x "$HOME/.local/bin/claude"
pass "stubbed claude, so nothing is downloaded from claude.ai"

head_ "Running scripts/get.sh"
# --no-wrapper keeps the run from shadowing `claude` in the container; the
# wrapper itself has its own coverage in smoke:bootstrap.
if sh "$REPO/scripts/get.sh" --no-wrapper; then
  pass "get.sh exited 0"
else
  fail "get.sh exited $?"
fi

head_ "What that should have produced"
command -v agent-bridge >/dev/null && pass "agent-bridge is on PATH" || fail "no agent-bridge command"
[ ! -d "$HOME/agent-bridge" ] && pass "did not clone into ~/agent-bridge" || fail "left a checkout in ~/agent-bridge"

[ -x "$HOME/.venvs/agent-bridge/bin/python" ] \
  && pass "virtualenv built" || fail "no virtualenv"
"$HOME/.venvs/agent-bridge/bin/python" -c 'import discord, dotenv' 2>/dev/null \
  && pass "dependencies importable" || fail "venv cannot import discord / dotenv"
grep -qE 'notify\.(sh|py)' "$HOME/.claude/settings.json" 2>/dev/null \
  && pass "hooks wired" || fail "hooks were not wired"

head_ "Running it a second time updates in place"
if sh "$REPO/scripts/get.sh" --no-wrapper >/tmp/second-install.log 2>&1; then
  pass "second run exited 0"
else
  fail "second run exited non-zero"
  tail -20 /tmp/second-install.log
fi

head_ "It does not create a checkout, even if told a directory"
rm -rf /tmp/occupied && mkdir -p /tmp/occupied && touch /tmp/occupied/mine.txt
if AGENT_BRIDGE_DIR=/tmp/occupied sh "$REPO/scripts/get.sh" --no-wrapper >/tmp/occupied.log 2>&1; then
  pass "second-style run with a stray AGENT_BRIDGE_DIR still exited 0"
else
  fail "install failed when AGENT_BRIDGE_DIR pointed at an existing directory"
fi
[ -f /tmp/occupied/mine.txt ] && pass "left that directory alone" || fail "deleted someone's files"
[ ! -d /tmp/occupied/.git ] && pass "did not turn it into a clone" || fail "cloned into AGENT_BRIDGE_DIR"

if [ "${AB_CHECK_PUBLIC_URL:-0}" = "1" ]; then
  head_ "The URL in the README still resolves"
  url="https://gitlab.com/shashankchakraborty712005/agent-bridge/-/raw/main/scripts/get.sh"
  code="$(curl -s -o /tmp/published.sh -w '%{http_code}' "$url")"
  if [ "$code" = "200" ]; then
    pass "published get.sh is reachable"
    diff -q /tmp/published.sh "$REPO/scripts/get.sh" >/dev/null \
      && pass "published copy matches this commit" \
      || fail "published get.sh differs from this commit"
  else
    fail "the install URL returned $code -- the README one-liner is broken"
  fi
fi

printf '\n'
[ "$FAILED" -eq 0 ] && { echo "install smoke: passed"; exit 0; }
echo "install smoke: failed"
exit 1
