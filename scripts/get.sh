#!/bin/sh
# One-command install for macOS, Linux, and an existing WSL distro:
#
#   curl -fsSL https://gitlab.com/shashankchakraborty712005/agent-bridge/-/raw/main/scripts/get.sh | sh
#
# Clones the repo and hands over to bootstrap.sh, which does the real work and
# is safe to re-run. Windows without WSL starts from install.ps1 instead --
# see the README.
#
# Overrides, all optional:
#   AGENT_BRIDGE_DIR    where to put it        (default ~/agent-bridge)
#   AGENT_BRIDGE_REPO   what to clone
#   AGENT_BRIDGE_REF    branch, tag or commit  (default main)
#
# POSIX sh on purpose: this is the one file people run before they have
# anything, so it must work under dash and ash, not just bash.
set -eu

REPO_URL="${AGENT_BRIDGE_REPO:-https://gitlab.com/shashankchakraborty712005/agent-bridge.git}"
REF="${AGENT_BRIDGE_REF:-main}"
DIR="${AGENT_BRIDGE_DIR:-$HOME/agent-bridge}"

say()  { printf '\n==> %s\n' "$1"; }
die()  { printf 'get.sh: %s\n' "$1" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then hint="sudo apt-get install -y $1"
  elif command -v dnf >/dev/null 2>&1;   then hint="sudo dnf install -y $1"
  elif command -v brew >/dev/null 2>&1;  then hint="brew install $1"
  else hint="install $1 with your package manager"
  fi
  die "$1 is required but not installed. Try: $hint"
}

main() {
  say "agent-bridge"
  need git

  if [ -d "$DIR/.git" ]; then
    printf '    updating the copy already in %s\n' "$DIR"
    git -C "$DIR" fetch --quiet origin "$REF" || die "could not fetch $REF from origin"
    git -C "$DIR" checkout --quiet FETCH_HEAD || die "could not check out $REF"
  elif [ -e "$DIR" ]; then
    die "$DIR already exists and is not a git clone. Move it, or set AGENT_BRIDGE_DIR."
  else
    printf '    cloning into %s\n' "$DIR"
    git clone --quiet "$REPO_URL" "$DIR" || die "could not clone $REPO_URL"
    git -C "$DIR" checkout --quiet "$REF" 2>/dev/null || true
  fi

  [ -f "$DIR/scripts/bootstrap.sh" ] || die "$DIR does not look like agent-bridge"

  # Piped into sh, stdin is the script itself rather than the keyboard, so
  # bootstrap.sh would silently skip the guided Discord setup. Hand it the
  # terminal back where there is one.
  say "handing over to bootstrap.sh"
  if [ ! -t 0 ] && [ -r /dev/tty ]; then
    bash "$DIR/scripts/bootstrap.sh" "$@" < /dev/tty
  else
    bash "$DIR/scripts/bootstrap.sh" "$@"
  fi
}

# Called on the last line so a download that truncates mid-flight defines main
# and then does nothing, instead of running half an installer.
main "$@"
