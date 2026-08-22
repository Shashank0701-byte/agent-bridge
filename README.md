# agent-bridge

Get a Discord DM when your coding agent (Claude Code, Codex, etc.) is blocked
waiting on you, reply from your phone, and have that reply typed straight back
into the session -- no need to be at your keyboard.

## How it works

The whole thing hinges on one idea: run the agent inside **tmux**, then treat
the terminal itself as the integration point instead of hooking into each
tool's internals differently. That's what makes it work the same way for
Claude Code, Codex, or anything else you run in a terminal.

```
 you AFK                         tmux session "myproject"
   |                                    |
   |  Discord DM  <----- notify.sh <----+  Notification hook fires
   |                                       (Claude Code is waiting on you)
   |
   |  you reply on phone
   v
 bot.py ----> load-buffer + paste-buffer -t myproject, then Enter
                                    |
                                    v
                          agent resumes as if you typed it
```

## Requirements

- **tmux.** This is the load-bearing dependency and it has no Windows build.
  On Windows, run everything inside WSL2 -- the agent, tmux, and the bot all
  need to live on the same machine.
- **Python 3.8+** (`python3` or `python`, either is detected).
- A Discord account.

```bash
# WSL2 / Ubuntu
sudo apt update && sudo apt install -y tmux python3 python3-pip
```

## Folder structure

```
agent-bridge/
├── README.md
├── .env.example                      # copy to .env and fill in
├── requirements.txt
├── config/
│   └── claude-settings.snippet.json  # merged into ~/.claude/settings.json
├── hooks/
│   └── notify.sh                     # OUTBOUND: hook -> Discord DM
├── bot/
│   └── bot.py                        # INBOUND: Discord DM -> tmux
├── poller/
│   └── watch_pane.sh                 # fallback for agents with no hook system
└── scripts/
    ├── start_session.sh              # launch a named tmux session running the agent
    └── install.sh                    # one-time setup
```

## Creating the Discord bot

1. Go to the [Developer Portal](https://discord.com/developers/applications) ->
   **Create App**, give it a name.
2. **Bot** tab -> **Reset Token** -> copy it. That's `DISCORD_BOT_TOKEN`.
   Leave all three Privileged Gateway Intents **off** -- you don't need them
   (see below). Treat this token like a password: it is full control of the bot.
3. **Installation** tab -> under *Guild Install*, set scope `bot` and tick the
   **Send Messages** permission. Copy the **Install Link** at the top.
4. A bot can only DM you if you share a server with it, so make a throwaway
   private server (**+** in the sidebar -> Create My Own), then open the install
   link, choose **Add to server**, and pick it. You never have to use that
   server again -- it exists purely to establish the shared membership.
5. In that server: **right-click it -> Privacy Settings -> Direct Messages** on.
   If this is off, the bot's DM is rejected with a 403 even though everything
   else is configured correctly. This is the single most common setup trap.
6. Get your own user ID: **User Settings -> Advanced -> Developer Mode** on,
   then right-click your own name -> **Copy User ID**. That's `DISCORD_USER_ID`.

> **Why no Message Content intent?** It's a privileged intent normally needed
> to read message text, but Discord documents an explicit exception for
> "content in DMs with the app." Since this bot only ever listens in your DMs,
> it gets full message content without it -- one less approval to chase.

## Setup

```bash
cp .env.example .env      # fill in DISCORD_BOT_TOKEN and DISCORD_USER_ID

# Ubuntu 24.04+ and Debian 12+ enforce PEP 668, so a system-wide `pip install`
# is refused with "externally-managed-environment". Use a venv.
python3 -m venv ~/.venvs/agent-bridge
~/.venvs/agent-bridge/bin/pip install -r requirements.txt

./scripts/install.sh      # wires the Notification/Stop hooks into ~/.claude/settings.json
```

Only `bot.py` needs those packages. `notify.sh` is pure standard library, so the
hook keeps working regardless of which interpreter fires it.

`install.sh` backs up your existing `settings.json` first, substitutes this
repo's real path into the hook commands, and appends its hooks alongside any
you already had rather than replacing them. Re-running it is safe -- it
replaces its own previous entries instead of stacking up duplicates.

Then run the two long-lived processes:

```bash
~/.venvs/agent-bridge/bin/python bot/bot.py   # wrap in systemd/pm2/tmux so it survives reboots
./scripts/start_session.sh myproject          # defaults to `claude`; 2nd arg for e.g. codex
```

A simple way to keep the bot alive is to give it its own tmux session:

```bash
tmux new -d -s bridge-bot "cd $PWD && ~/.venvs/agent-bridge/bin/python bot/bot.py"
```

## Complete flow

1. `start_session.sh myproject` opens tmux session `myproject` and launches
   the agent inside it.
2. You work as normal. The agent hits something it needs your input on ->
   Claude Code's `Notification` hook fires -> `notify.sh` reads the hook's
   JSON off stdin, extracts the question, records `myproject` as the
   "last active session" in a small state file, and DMs you.
3. You're away -> phone buzzes: `🟡 [myproject] Needs input: ...`.
4. You reply in the DM -- plain text if it's your only session, or
   `!myproject your reply` to target explicitly when you've got more than one
   running. `!sessions` lists what's live.
5. `bot.py` receives it, verifies the sender is you, resolves the target
   session, and types the text into that pane followed by Enter.
6. The agent sees the input exactly as if you'd typed it and continues.
7. When the whole task finishes, the `Stop` hook fires ->
   `✅ [myproject] Task finished.`

For agents without a native hook system (Codex, as far as could be confirmed
at the time this was written -- worth checking their current docs), use
`poller/watch_pane.sh <session-name>` instead of relying on hooks. It polls
the pane, and once output goes idle for a few seconds and the last line
matches a prompt-like pattern, it fires the same `notify.sh`. It's a
heuristic (tune `PROMPT_REGEX` for your tool's actual prompts), not as
precise as a real hook.

## Verifying it works

You don't need a real agent run to test either leg:

```bash
echo '{"message":"test ping"}' | ./hooks/notify.sh input   # -> a DM should arrive
```

Then, in the DM, send `!sessions` -- it should list your live tmux sessions.
To check the reply path end to end:

```bash
tmux new -d -s scratch
# reply in the DM, then:
tmux capture-pane -t scratch -p | tail -3                  # your text should be in the pane
```

## Design decisions

- **tmux as the universal interface.** Every coding-agent CLI is just a
  terminal program underneath. Instead of learning each tool's internal API,
  the bridge types into the terminal -- works identically no matter which
  agent you're running.
- **Native hooks where available, polling where not.** Claude Code's
  `Notification` event fires exactly when it's blocked on you -- reliable, no
  guesswork. Tools without that get the pane-watching fallback instead.
- **DMs rather than a channel.** Keeps the privileged Message Content intent
  out of the picture entirely, and means plain-text replies work without
  having to @mention the bot every time.
- **Paste buffers, not `send-keys <text>`.** `send-keys` runs your text
  through tmux's own argument parser, which mangles real replies three
  different ways: one starting with `-` is rejected as an invalid flag
  ([tmux#4408](https://github.com/tmux/tmux/issues/4408)), one that happens to
  read `Enter` or `Up` is sent as that keypress instead of the word, and a
  trailing `;` is read as a command separator
  ([tmux#1849](https://github.com/tmux/tmux/issues/1849)). Loading the text
  into a paste buffer from stdin bypasses that parser completely.
- **`!` prefix, not `/`.** A leading slash triggers Discord's native
  slash-command autocomplete, which pops up an unhelpful "no commands match"
  every time you start a reply.
- **One long-running bot, not one per session.** Sessions are tracked by tmux
  session name; a state file remembers whichever session pinged last, so a
  plain reply auto-targets it. `!session-name text` overrides that when
  multiple sessions are live.
- **User ID allowlist, no exceptions.** Typing into a terminal is effectively
  remote shell access to your machine, so the bot drops any message that isn't
  a DM from your own user ID.
- **Runs on the same host as tmux.** tmux is driven locally, not over the
  network, so the bridge has to run wherever your sessions actually live. If
  your laptop sleeps when you walk away, put this on a small always-on VPS and
  SSH/tmux into your real work from there instead.

## Known limitations

- The poller fallback can misfire on tools whose prompts don't match
  `PROMPT_REGEX` -- expect to tune it per-tool.
- No message queue -- if the bot process is down when a notification fires,
  that ping is lost (though the session itself just stays paused, nothing is
  lost on the agent side).
- Notifications are truncated to Discord's 2000-character message limit.
- Single-user only by design (one allowlisted user ID). Extending to a team
  would need per-user session ownership, which this doesn't attempt.
- **If the agent has exited and the pane is sitting at a bare shell, whatever
  you send is executed as a shell command.** That's inherent to the approach,
  not a bug -- but it's why the allowlist matters and why the bot token
  belongs in `.env` and nowhere else.
