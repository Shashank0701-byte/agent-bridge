#!/usr/bin/env bash
# Installs the transparent `claude` wrapper so the bridge turns itself on.
#
#   ./scripts/install_wrapper.sh            # install
#   ./scripts/install_wrapper.sh --uninstall
#
# The wrapper goes in ~/.agent-bridge/bin, NOT over ~/.local/bin/claude, so
# Claude Code's auto-updater keeps managing its own launcher untouched.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$HOME/.agent-bridge/bin"
MARKER="# added by agent-bridge install_wrapper.sh"

# The PATH line has to go in BOTH files. Ubuntu's ~/.profile sources ~/.bashrc
# first and only then prepends ~/.local/bin, so a line added to .bashrc alone
# ends up BEHIND the real claude in login shells (the usual case when you open
# a WSL terminal) and the wrapper would silently never run. .bashrc covers
# non-login interactive shells, such as tmux panes.
RC_FILES=("$HOME/.bashrc" "$HOME/.profile")

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$BIN/claude"
  for rc in "${RC_FILES[@]}"; do
    [ -f "$rc" ] || continue
    grep -v "agent-bridge/bin" "$rc" | grep -vF "$MARKER" > "$rc.tmp"
    mv "$rc.tmp" "$rc"
  done
  echo "wrapper removed. Open a new shell; 'command -v claude' should point at ~/.local/bin/claude again."
  exit 0
fi

# Resolve the REAL claude, ignoring any wrapper already on PATH.
REAL=""
for cand in "$HOME/.local/bin/claude" /usr/local/bin/claude /usr/bin/claude; do
  [ -x "$cand" ] && { REAL="$cand"; break; }
done
[ -n "$REAL" ] || { echo "could not find the real claude binary" >&2; exit 1; }
echo "real claude : $REAL"

mkdir -p "$BIN"
sed -e "s|__AGENT_BRIDGE_DIR__|$REPO|g" -e "s|__REAL_CLAUDE__|$REAL|g" \
    "$REPO/scripts/claude-wrapper.sh" > "$BIN/claude"
chmod +x "$BIN/claude"
echo "wrapper     : $BIN/claude"

for rc in "${RC_FILES[@]}"; do
  if grep -q "agent-bridge/bin" "$rc" 2>/dev/null; then
    echo "PATH        : already configured in $rc"
  else
    printf '\n%s\nexport PATH="$HOME/.agent-bridge/bin:$PATH"\n' "$MARKER" >> "$rc"
    echo "PATH        : prepended ~/.agent-bridge/bin in $rc"
  fi
done

# Prove it: a fresh login shell must resolve `claude` to the wrapper, or the
# whole thing is a no-op.
RESOLVED="$(bash -lic 'command -v claude' 2>/dev/null | tail -1 | tr -d '\r')"
echo "PATH check  : login shell resolves claude -> $RESOLVED"
if [ "$RESOLVED" != "$BIN/claude" ]; then
  echo "WARNING: expected $BIN/claude. The wrapper will not take effect." >&2
fi

echo ""
echo "Done. Open a NEW shell, then:"
echo "  command -v claude     -> should print $BIN/claude"
echo "  cd ~/any/project && claude"
echo ""
echo "Escape hatches:"
echo "  AGENT_BRIDGE_WRAP=0 claude    # skip the wrapper once"
echo "  $REAL                          # run the real binary directly"
echo "  ./scripts/install_wrapper.sh --uninstall"
