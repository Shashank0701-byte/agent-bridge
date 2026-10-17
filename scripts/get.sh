#!/bin/sh
# Install the agent-bridge command without leaving a git checkout behind:
#
#   curl -fsSL https://gitlab.com/shashankchakraborty712005/agent-bridge/-/raw/main/scripts/get.sh | sh
#
# That installs with pipx (or uv) and then runs `agent-bridge setup`.
# Until the name is on PyPI the package is fetched from git. A local directory
# in AGENT_BRIDGE_REPO is installed as itself, which is how CI tests a commit
# without cloning it a second time.
#
#   AGENT_BRIDGE_REPO   git URL or a local checkout
#   AGENT_BRIDGE_REF    branch, tag or commit (default main; git URLs only)
#
# POSIX sh on purpose: this is the one file people run before they have
# anything, so it must work under dash and ash, not just bash.
set -eu

REPO_URL="${AGENT_BRIDGE_REPO:-https://gitlab.com/shashankchakraborty712005/agent-bridge.git}"
REF="${AGENT_BRIDGE_REF:-main}"

say()  { printf '\n==> %s\n' "$1"; }
die()  { printf 'get.sh: %s\n' "$1" >&2; exit 1; }

# A checkout path is installed from disk. Anything else is a git URL.
spec() {
  if [ -d "$REPO_URL" ]; then
    printf '%s\n' "$REPO_URL"
  else
    printf 'git+%s@%s\n' "$REPO_URL" "$REF"
  fi
}

install_package() {
  spec_value="$(spec)"
  if command -v pipx >/dev/null 2>&1; then
    pipx install --force "$spec_value"
  elif command -v uv >/dev/null 2>&1; then
    uv tool install --reinstall "$spec_value"
  else
    die "pipx or uv is required, so this can install a command instead of cloning. Try: pip install pipx"
  fi
}

main() {
  say "agent-bridge"
  install_package

  # pipx and uv put the command in ~/.local/bin, which a fresh shell may not
  # have on PATH yet.
  if ! command -v agent-bridge >/dev/null 2>&1 && [ -x "$HOME/.local/bin/agent-bridge" ]; then
    PATH="$HOME/.local/bin:$PATH"
    export PATH
  fi
  command -v agent-bridge >/dev/null 2>&1 \
    || die "the package installed, but agent-bridge is not on PATH. Open a new shell, or add ~/.local/bin."

  # Piped into sh, stdin is the script itself rather than the keyboard, so
  # setup would silently skip the guided Discord setup. Hand it the terminal
  # back where there is one.
  #
  # Opening /dev/tty is the test, not `[ -r /dev/tty ]`. The latter calls
  # access(), which answers a question about permissions -- and it says yes on
  # a process with no controlling terminal, where the open then fails with
  # ENXIO. That is every container, cron job and `ssh host '... | sh'`.
  say "handing over to agent-bridge setup"
  if [ ! -t 0 ] && (exec 3</dev/tty) 2>/dev/null; then
    agent-bridge setup "$@" < /dev/tty
  else
    agent-bridge setup "$@"
  fi
}

# Called on the last line so a download that truncates mid-flight defines main
# and then does nothing, instead of running half an installer.
main "$@"
