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
import re
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

# Two ways to aim a reply at a session. The "[name] text" form matters most:
# it mirrors the notification being replied to ("[PromptWall] Needs input: ..."),
# which is the format people naturally copy. Session names never contain
# spaces (see lib/session_name.sh), so restricting the captured name to
# [A-Za-z0-9_-] keeps ordinary prose like "[see below] do it" from being
# mistaken for a target.
TARGET_PATTERNS = (
    re.compile(r"^!\s*([A-Za-z0-9_-]+)\s*(.*)$", re.DOTALL),
    re.compile(r"^\[\s*([A-Za-z0-9_-]+)\s*\]\s*(.*)$", re.DOTALL),
)

# Every message the bridge sends is tagged "[session] ...". Replying to one
# in Discord is the most natural way to answer it, so pull the session name
# back out of whatever message was replied to.
SESSION_TAG_RE = re.compile(r"\[([A-Za-z0-9_-]+)\]")

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


async def session_from_reply(message, sessions):
    """Resolve the target session from a Discord reply, or None.

    Replying to "[PromptWall] Needs input: ..." should answer PromptWall without
    having to retype the name. The referenced message is usually already cached
    on `reference.resolved`; if not, fetch it. A deleted referenced message
    resolves to DeletedReferencedMessage rather than a Message, so anything that
    is not a Message is treated as unusable.
    """
    ref = message.reference
    if ref is None or ref.message_id is None:
        return None

    referenced = ref.resolved
    if referenced is not None and not isinstance(referenced, discord.Message):
        return None                      # deleted
    if referenced is None:
        try:
            referenced = await message.channel.fetch_message(ref.message_id)
        except Exception as e:
            log.warning("could not fetch replied-to message: %s", e)
            return None

    match = SESSION_TAG_RE.search(referenced.content or "")
    if not match:
        return None
    name = match.group(1)
    return next((s for s in sessions if s.lower() == name.lower()), None)


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

    # Explicit targeting: "!name your reply" or "[name] your reply".
    target = None
    for pattern in TARGET_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        candidate, rest = m.group(1), m.group(2).strip()
        if candidate.lower() == "sessions":
            await message.channel.send(f"Live sessions: {', '.join(sessions) or 'none'}")
            return
        # Case-insensitive: phone keyboards capitalise the first letter.
        target = next((s for s in sessions if s.lower() == candidate.lower()), None)
        if target is None:
            # Refuse rather than fall through to the last-pinged session.
            # Falling through types this text into a DIFFERENT live agent,
            # which is far worse than making you retype it.
            await message.channel.send(
                f"No session named `{candidate}`. Live sessions: "
                f"{', '.join(sessions) or 'none'}.\nNothing was sent."
            )
            return
        text = rest
        break

    # Next best: a Discord reply to one of the bridge's own messages.
    if target is None:
        target = await session_from_reply(message, sessions)

    if target is None:
        target = read_state().get("last_session")

    if not target or target not in sessions:
        await message.channel.send(
            f"No active tmux session to target. Live sessions: {', '.join(sessions) or 'none'}\n"
            f"Reply to one of my messages, or use `[session-name] your reply`."
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
