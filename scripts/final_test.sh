#!/usr/bin/env bash
# Post-login end-to-end check: proves the Notification/Stop hooks reach Discord.
# Run this after `claude auth login` (or /login inside a claude session).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$HOME/.local/bin:$PATH"
VENV="$HOME/.venvs/agent-bridge/bin/python"

if ! command -v claude >/dev/null; then echo "claude not on PATH"; exit 1; fi
if ! grep -q '"' ~/.claude/.credentials.json 2>/dev/null; then
  echo "Not logged in yet. Run:  claude auth login"; exit 1
fi

# Make sure the bot is up so replies work.
if ! tmux has-session -t bridge-bot 2>/dev/null; then
  echo "starting bot in tmux session 'bridge-bot'..."
  tmux new -d -s bridge-bot "cd $PWD && $VENV bot/bot.py 2>&1 | tee /tmp/bot.log"
  sleep 6
fi

echo "starting a real claude session in tmux 'myproject'..."
tmux kill-session -t myproject 2>/dev/null
./scripts/start_session.sh myproject
sleep 5

echo ""
echo "Now do ONE of these:"
echo "  a) tmux attach -t myproject   and ask claude something that needs approval"
echo "     (e.g. 'run: rm -rf /tmp/demo') -> Notification hook -> Discord DM"
echo "  b) headless Stop-hook test, no attach needed:"
echo "       TMUX_SESSION_NAME=myproject claude -p 'say hi' >/dev/null"
echo "     -> should DM you: 'Task finished.'"
echo ""
echo "Then reply in Discord and watch it land:  tmux attach -t myproject"
