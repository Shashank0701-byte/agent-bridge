"""
Inbound leg of the bridge.

Connects to Discord, watches for DMs from you, and types them into the right
tmux session. Only your own user ID is honoured -- everything else is dropped.

Run this as a persistent process (systemd/pm2/tmux) on the SAME machine where
your tmux sessions live: tmux is driven locally, not over the network.
"""
import json
import logging
import os
import subprocess
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["DISCORD_USER_ID"])

# "!" rather than "/": a leading slash triggers Discord's native slash-command
# autocomplete, which pops up an unhelpful "no commands match" every time you
# start a reply.
PREFIX = "!"
BUFFER = "agent-bridge"

STATE_FILE = Path(
    os.environ.get("AGENT_BRIDGE_STATE", "~/.agent-bridge/state.json")
).expanduser()
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent-bridge")


def read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def tmux_sessions() -> list[str]:
    try:
        out = subprocess.run(
            ["tmux", "list-sessions", "-F", "#S"],
            capture_output=True, text=True, check=True,
        )
        return [s for s in out.stdout.strip().splitlines() if s]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def type_into_session(target: str, text: str) -> tuple[bool, str]:
    """Type `text` into the pane, then press Enter.

    Routed through a paste buffer loaded from stdin rather than the more
    obvious `tmux send-keys <text>`, because send-keys puts the text through
    tmux's own argument parser and that mangles real replies three ways:
    a reply starting with "-" is rejected as an invalid flag (tmux#4408),
    a reply that happens to read "Enter" or "Up" is sent as that keypress
    instead of the word, and a trailing ";" is read as a command separator
    (tmux#1849). Buffer contents loaded from stdin never touch that parser.
    """
    if text:
        load = subprocess.run(
            ["tmux", "load-buffer", "-b", BUFFER, "-"],
            input=text.encode(), capture_output=True,
        )
        if load.returncode != 0:
            return False, load.stderr.decode(errors="replace").strip() or "load-buffer failed"

        paste = subprocess.run(
            ["tmux", "paste-buffer", "-d", "-b", BUFFER, "-t", target],
            capture_output=True, text=True,
        )
        if paste.returncode != 0:
            return False, paste.stderr.strip() or "paste-buffer failed"

    # Sent separately so it is always a real Enter keypress, never literal text.
    enter = subprocess.run(
        ["tmux", "send-keys", "-t", target, "Enter"],
        capture_output=True, text=True,
    )
    if enter.returncode != 0:
        return False, enter.stderr.strip() or "send-keys Enter failed"
    return True, ""


# Privileged intents stay off. Discord always delivers full message content for
# DMs with the bot, and DMs are the only place this listens.
client = discord.Client(intents=discord.Intents.default())


@client.event
async def on_ready():
    log.info("connected as %s -- accepting DMs from user_id=%s",
             client.user, ALLOWED_USER_ID)


@client.event
async def on_message(message: discord.Message):
    # Ignore our own confirmations, or they feed straight back in.
    if message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return
    if message.author.id != ALLOWED_USER_ID:
        log.warning("Ignored DM from unauthorized user %s", message.author.id)
        return

    text = message.content.strip()
    if not text:
        return
    sessions = tmux_sessions()

    # Explicit targeting: "!session-name your reply text"
    target = None
    if text.startswith(PREFIX):
        parts = text[len(PREFIX):].split(" ", 1)
        candidate = parts[0]
        if candidate == "sessions":
            await message.channel.send(f"Live sessions: {', '.join(sessions) or 'none'}")
            return
        if candidate in sessions:
            target = candidate
            text = parts[1].strip() if len(parts) > 1 else ""

    if target is None:
        target = read_state().get("last_session")

    if not target or target not in sessions:
        await message.channel.send(
            f"No active tmux session to target. Live sessions: {', '.join(sessions) or 'none'}\n"
            f"Use `{PREFIX}session-name your reply` to pick one explicitly."
        )
        return

    ok, err = type_into_session(target, text)
    if not ok:
        log.error("send to %s failed: %s", target, err)
        await message.channel.send(f"⚠️ failed to send to [{target}]: {err}")
        return
    await message.channel.send(f"↩️ sent to [{target}]")


def main():
    client.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
