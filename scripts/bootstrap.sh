#!/usr/bin/env bash
# One-command setup for agent-bridge on Linux, macOS, or WSL.
#
#   ./scripts/bootstrap.sh              # everything
#   ./scripts/bootstrap.sh --no-wrapper # skip shadowing the `claude` command
#
# Idempotent: safe to re-run. Each step reports skipped / done, and the script
# ends with a checklist of what is and is not working.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$HOME/.venvs/agent-bridge"
WANT_WRAPPER=1
[ "${1:-}" = "--no-wrapper" ] && WANT_WRAPPER=0

FAILED=()
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$1"; }
skip() { printf '    %s\n' "$1"; }
bad()  { printf '    \033[31m%s\033[0m\n' "$1"; FAILED+=("$1"); }

IS_WSL=0
grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1

# ---------------------------------------------------------------- packages ---
step "System packages"
if command -v apt-get >/dev/null; then
  PKGS=(tmux python3 python3-venv python3-pip curl)
  [ "$IS_WSL" = 1 ] && PKGS+=(wslu)   # wslview: opens the Windows browser for login
  MISSING=()
  for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
  if [ ${#MISSING[@]} -eq 0 ]; then
    skip "already installed: ${PKGS[*]}"
  else
    ok "installing: ${MISSING[*]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}" >/dev/null \
      && ok "installed" || bad "apt-get install failed"
  fi
elif command -v dnf >/dev/null; then
  sudo dnf install -y -q tmux python3 python3-pip curl >/dev/null && ok "installed via dnf" || bad "dnf install failed"
elif command -v brew >/dev/null; then
  for p in tmux python3; do brew list "$p" >/dev/null 2>&1 || brew install "$p"; done
  ok "installed via brew"
else
  bad "no supported package manager (need apt, dnf, or brew) - install tmux and python3 manually"
fi
command -v tmux    >/dev/null && ok "tmux    $(tmux -V)"           || bad "tmux missing"
command -v python3 >/dev/null && ok "python3 $(python3 -V 2>&1)"   || bad "python3 missing"

# -------------------------------------------------------------------- venv ---
step "Python virtualenv"
if [ -x "$VENV/bin/python" ]; then
  skip "exists at $VENV"
else
  python3 -m venv "$VENV" && ok "created $VENV" || bad "could not create venv"
fi
if [ -x "$VENV/bin/pip" ]; then
  "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  "$VENV/bin/pip" install -q -r "$REPO/requirements.txt" \
    && ok "dependencies installed" || bad "pip install failed"
fi

# ------------------------------------------------------------ claude code ---
step "Claude Code"
if command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ]; then
  skip "already installed ($("${HOME}/.local/bin/claude" --version 2>/dev/null || claude --version 2>/dev/null))"
else
  if curl -fsSL https://claude.ai/install.sh -o /tmp/cc_install.sh \
     || curl -fsSL -4 --retry 3 --retry-all-errors https://claude.ai/install.sh -o /tmp/cc_install.sh; then
    bash /tmp/cc_install.sh >/dev/null 2>&1
    [ -x "$HOME/.local/bin/claude" ] && ok "installed $("$HOME/.local/bin/claude" --version)" \
      || bad "installer ran but claude is not at ~/.local/bin/claude"
  else
    bad "could not download the Claude Code installer (network?)"
  fi
fi
# ~/.local/bin must be on PATH for tmux panes to find claude.
if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  ok "added ~/.local/bin to PATH in ~/.bashrc"
fi
export PATH="$HOME/.local/bin:$PATH"

# ------------------------------------------------------------------- .env ---
step "Credentials"
if [ -f "$REPO/.env" ]; then
  skip ".env exists (leaving it alone)"
else
  cp "$REPO/.env.example" "$REPO/.env"
  ok "created .env from the example - you must fill in DISCORD_BOT_TOKEN and DISCORD_USER_ID"
fi
# A .env saved on Windows carries CRLF, which smuggles \r into the bot token and
# produces a 401 that looks exactly like a wrong token.
if [ -f "$REPO/.env" ] && LC_ALL=C grep -qU $'\r' "$REPO/.env" 2>/dev/null; then
  python3 - "$REPO/.env" <<'PY'
import sys
p = sys.argv[1]
b = open(p, "rb").read()
open(p, "wb").write(b.replace(b"\r\n", b"\n"))
PY
  ok "normalised CRLF line endings in .env"
fi

# ------------------------------------------------------------------ hooks ---
step "Claude Code hooks"
bash "$REPO/scripts/install.sh" >/dev/null 2>&1 \
  && ok "Notification + Stop hooks wired into ~/.claude/settings.json" \
  || bad "install.sh failed"

# ---------------------------------------------------------------- wrapper ---
step "Transparent \`claude\` wrapper"
if [ "$WANT_WRAPPER" = 1 ]; then
  bash "$REPO/scripts/install_wrapper.sh" >/dev/null 2>&1 \
    && ok "installed - typing \`claude\` anywhere now starts the bridge" \
    || bad "install_wrapper.sh failed"
else
  skip "skipped (--no-wrapper); use scripts/start_session.sh instead"
fi

# -------------------------------------------------------------------- bot ---
step "Bot"
if [ -f "$REPO/.env" ] && ! grep -q 'your-bot-token\|your_numeric' "$REPO/.env"; then
  bash "$REPO/scripts/bot_ctl.sh" restart >/dev/null 2>&1
  BOT_UP=0
  # Poll instead of sleeping a fixed time: launching the supervisor from a
  # /mnt drive is slow enough that a short fixed wait reports a false failure.
  for _ in $(seq 1 30); do
    # NB: capture first, then match. Testing a pipeline directly is a trap here:
    # `... | head -1 | grep -q` closes the pipe early, the upstream command dies
    # of SIGPIPE (141), and `set -o pipefail` reports the whole pipeline as
    # failed even when grep matched.
    BOT_STATUS="$(bash "$REPO/scripts/bot_ctl.sh" status 2>/dev/null)"
    case "$BOT_STATUS" in
      running*) BOT_UP=1; break ;;
    esac
    sleep 1
  done
  if [ "$BOT_UP" = 1 ]; then
    ok "running"
  else
    bad "bot did not start - check: $REPO/scripts/bot_ctl.sh logs"
  fi
else
  skip "not started: .env still has placeholder values"
fi

# ------------------------------------------------------------------ report ---
printf '\n\033[1m==================== summary ====================\033[0m\n'
chk() { printf '  %-38s %s\n' "$1" "$2"; }
chk "tmux"        "$(command -v tmux >/dev/null && tmux -V || echo MISSING)"
chk "python venv" "$([ -x "$VENV/bin/python" ] && echo OK || echo MISSING)"
chk "discord.py"  "$("$VENV/bin/python" -c 'import discord;print(discord.__version__)' 2>/dev/null || echo MISSING)"
chk "claude"      "$(claude --version 2>/dev/null || echo MISSING)"
chk "hooks wired" "$(grep -c notify.sh "$HOME/.claude/settings.json" 2>/dev/null || echo 0)"
chk "wrapper"     "$([ -x "$HOME/.agent-bridge/bin/claude" ] && echo OK || echo 'not installed')"
chk "logged in"   "$([ -f "$HOME/.claude/.credentials.json" ] && echo yes || echo 'NO')"
BOT_NOW="$(bash "$REPO/scripts/bot_ctl.sh" status 2>/dev/null)"
chk "bot"         "${BOT_NOW%%$'
'*}"

printf '\n'
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '\033[31mSome steps failed:\033[0m\n'
  for f in "${FAILED[@]}"; do printf '  - %s\n' "$f"; done
  printf '\n'
fi

printf '\033[1mNext:\033[0m\n'
n=1
if grep -q 'your-bot-token\|your_numeric' "$REPO/.env" 2>/dev/null; then
  printf '  %d. Fill in %s (see the README for how to create the Discord bot)\n' "$n" "$REPO/.env"; n=$((n+1))
  printf '  %d. Re-run this script to start the bot\n' "$n"; n=$((n+1))
fi
[ -f "$HOME/.claude/.credentials.json" ] || { printf '  %d. claude auth login\n' "$n"; n=$((n+1)); }
printf '  %d. Open a NEW shell, then: cd <any project> && claude\n' "$n"
[ ${#FAILED[@]} -eq 0 ] || exit 1
