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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

# Filled in by main() rather than read at import, so the pure helpers below
# (compose_answer, the target patterns) can be imported and unit tested with
# no token in the environment.
BOT_TOKEN = ""
ALLOWED_USER_ID = 0          # matches no Discord user, so an unstarted bot fails closed

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

# ask_options.sh stashes the AskUserQuestion payload here so a reply like
# "1:2,3" can be turned back into the option labels Claude actually expects.

# A pick looks like 1:2 or 1.2, with commas for multi-select: 1:2,3
PICK_RE = re.compile(r"(\d+)\s*[:.]\s*((?:\d+\s*,\s*)*\d+)")

# Modal selectors render their choices as a numbered list, with the highlighted
# one marked: "❯ 1. Yes, I trust this folder" / "  2. No, exit".
OPTION_RE = re.compile(r"^\s*(?P<marker>[❯>])?\s*(?P<number>\d{1,2})\.\s+(?P<label>\S.*?)\s*$")

# "pick 2", "!pick 2". A bare "2" also counts, but only while a prompt is
# actually on screen -- see on_message.
SELECT_CMD_RE = re.compile(r"^!?\s*pick\s+(\d{1,2})$", re.I)
BARE_NUMBER_RE = re.compile(r"^(\d{1,2})$")

# "!run <command>": type this even though the pane is at a shell.
FORCE_RE = re.compile(r"^!\s*run\s+(.+)$", re.I | re.DOTALL)

# Buttons on a question card. ab:q:<session>:<question>:<option>, 1-based.
BUTTON_ID_RE = re.compile(r"^ab:q:([A-Za-z0-9_-]+):(\d{1,2}):(\d{1,2})$")

# If the agent has exited, the pane is a shell and anything typed is run as a
# command. Which command is in the pane is the only reliable way to tell.
#
# A denylist of shells, not an allowlist of agents, and the difference matters:
# tmux reports the pane's *foreground* command, so a pane busy running `npm` or
# `sleep` reports that rather than the agent -- an allowlist would refuse those.
# The bridge is also meant to work with any CLI agent, and those cannot be
# enumerated. Shells can.
SHELL_COMMANDS = frozenset({
    "bash", "sh", "zsh", "fish", "dash", "ash", "ksh", "mksh", "tcsh", "csh",
    "pwsh", "powershell", "cmd", "nu", "xonsh", "elvish",
})


def pane_command(target: str) -> str:
    """The command running in the pane right now, or "" if it cannot be read."""
    out = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{pane_current_command}"],
        capture_output=True, text=True,
    )
    return out.stdout.strip() if out.returncode == 0 else ""

STATE_FILE = Path(
    os.environ.get("AGENT_BRIDGE_STATE", "~/.agent-bridge/state.json")
).expanduser()
QUESTION_DIR = STATE_FILE.parent / "questions"

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


# Claude Code's modal selectors (plan approval, trust prompt, question cards)
# all end with a footer like "Enter to select . Esc to cancel".
#
# How they consume input, measured against Claude Code 2.1.241 using the folder
# trust prompt, whose option 2 is "No, exit" and therefore reports its own
# outcome. Re-check this if the mapping ever stops behaving:
#
#   send-keys "2"          selects option 2 immediately -- no Enter needed
#   paste-buffer "2"       also selects option 2
#   paste-buffer "hello"   selects the HIGHLIGHTED option, with no Enter at all
#   send-keys Down         moves the marker, leaves the prompt open
#   send-keys Space        ignored
#   send-keys Escape       dismisses (on the trust prompt, that exits Claude)
#
# The third line is the dangerous one, and it is why nothing may be pasted into
# a pane until the widget is verifiably gone: pasting ordinary prose is enough
# to approve a plan. The first line is what makes choose_option simple -- one
# keystroke, no cursor arithmetic to get wrong.
SELECTOR_RE = re.compile(r"Enter to (select|confirm)|Esc to cancel", re.I)

# Long enough for a slow render, short enough that a stuck prompt is reported
# rather than waited on. The pane settles in under 50ms in practice.
SETTLE_TIMEOUT = 2.0
SETTLE_POLL = 0.05


def capture_pane(target: str) -> str:
    """What is on screen in this pane right now, or "" if it cannot be read."""
    out = subprocess.run(["tmux", "capture-pane", "-t", target, "-p"],
                         capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def pane_has_selector(target: str) -> bool:
    """True if a modal selector is currently on screen in this pane."""
    tail = "\n".join(capture_pane(target).strip().splitlines()[-15:])
    return bool(SELECTOR_RE.search(tail))


def pane_options(target: str) -> tuple[list[tuple[int, str]], int | None]:
    """The numbered choices on screen, and which one is highlighted.

    Returns ([], None) when no selector is open, so callers can treat "nothing
    to choose from" and "cannot read the pane" the same way.
    """
    lines = capture_pane(target).strip().splitlines()
    tail = lines[-15:]
    if not SELECTOR_RE.search("\n".join(tail)):
        return [], None

    options, highlighted = [], None
    for line in tail:
        m = OPTION_RE.match(line)
        if not m:
            continue
        number = int(m.group("number"))
        options.append((number, m.group("label")))
        if m.group("marker"):
            highlighted = number
    return options, highlighted


def wait_for_selector_gone(target: str, timeout: float = SETTLE_TIMEOUT) -> bool:
    """Poll until no selector is on screen. False means one is still there."""
    deadline = time.monotonic() + timeout
    while True:
        if not pane_has_selector(target):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(SETTLE_POLL)


def choose_option(target: str, number: int) -> tuple[bool, str]:
    """Choose a numbered option by pressing its digit.

    Deliberately not arrow keys: a digit selects outright (see the table
    above), so there is no cursor position to track and no Enter to send --
    the two things that made the earlier auto-approval bug possible.
    """
    options, _ = pane_options(target)
    if not options:
        return False, "there is no prompt on screen to choose from"
    if not 1 <= number <= 9:
        # Two digits would be two keystrokes, and the first one would already
        # have selected something. Refuse rather than guess.
        return False, "only options 1-9 can be chosen this way"
    label = next((text for num, text in options if num == number), None)
    if label is None:
        listing = ", ".join(f"{num}. {text}" for num, text in options)
        return False, f"there is no option {number}. On screen: {listing}"

    sent = subprocess.run(["tmux", "send-keys", "-t", target, str(number)],
                          capture_output=True, text=True)
    if sent.returncode != 0:
        return False, sent.stderr.strip() or "send-keys failed"
    if not wait_for_selector_gone(target):
        return False, "the prompt is still on screen -- nothing was chosen"
    return True, label


def format_options(options: list[tuple[int, str]], highlighted: int | None) -> str:
    """The on-screen choices, as a line that fits in a DM."""
    parts = [f"{'**' if num == highlighted else ''}{num}. {text}"
             f"{'**' if num == highlighted else ''}"
             for num, text in options]
    return " · ".join(parts)


def type_into_session(target: str, text: str, dismiss_first: bool = False) -> tuple[bool, str]:
    """Type `text` into the pane, then press Enter.

    Routed through a paste buffer loaded from stdin rather than the more
    obvious `tmux send-keys <text>`, because send-keys puts the text through
    tmux's own argument parser and that mangles real replies three ways:
    a reply starting with "-" is rejected as an invalid flag (tmux#4408),
    a reply that happens to read "Enter" or "Up" is sent as that keypress
    instead of the word, and a trailing ";" is read as a command separator
    (tmux#1849). Buffer contents loaded from stdin never touch that parser.
    """
    # A trailing newline in the buffer submits on its own; the explicit Enter
    # below would then be a stray keypress that can select an option on whatever
    # prompt appears next. Seen in testing: it silently answered a question.
    text = text.rstrip("\r\n")

    if dismiss_first:
        # A prompt is open. Esc closes it and returns the pane to the normal
        # input box, so the answer can be typed as an ordinary message. Chosen
        # over driving the widget's checkboxes with arrow keys because the
        # layout changes between versions; the input box does not.
        subprocess.run(["tmux", "send-keys", "-t", target, "Escape"],
                       capture_output=True, text=True)
        # Verified, not slept on. Pasting into a widget that is still up selects
        # the highlighted option even without an Enter -- on a plan approval
        # that approves it. Refusing to type is always recoverable; typing into
        # a live widget is not.
        if not wait_for_selector_gone(target):
            return False, ("a prompt is still on screen and would have consumed "
                           "this reply -- nothing was sent. Use `pick <n>`, or "
                           "answer it in the terminal.")

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


def load_pending_question(session):
    """The AskUserQuestion payload waiting on this session, or None."""
    path = QUESTION_DIR / f"{session}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def clear_pending_question(session):
    try:
        (QUESTION_DIR / f"{session}.json").unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("could not clear pending question for %s: %s", session, e)


def audit_path():
    """Local JSONL of every injection attempt. Never leaves the machine."""
    override = os.environ.get("AGENT_BRIDGE_AUDIT")
    if override:
        return Path(override).expanduser()
    return STATE_FILE.parent / "audit.jsonl"


def append_audit(record):
    """Append one JSON object. A logging failure must not block the reply."""
    try:
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **record}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("could not write audit log: %s", e)


def parse_button_id(custom_id):
    """(session, question, option) from a card button, or None."""
    match = BUTTON_ID_RE.match(custom_id or "")
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def decide_button(custom_id, sessions, pending, pane):
    """What a question-card tap is allowed to do. None if it is not our button.

    ok means the caller may type `text` into `session`. A refusal still names
    the session and the text it would have typed, so the audit log can record
    the attempt. Nothing here touches tmux.
    """
    parsed = parse_button_id(custom_id)
    if parsed is None:
        return None
    name, qi, oi = parsed
    session = next((s for s in sessions if s.lower() == name.lower()), None)
    if session is None:
        return {"ok": False, "session": name, "text": "", "detail": "no-session", "pane": pane}

    questions = (pending or {}).get("questions") or []
    if not questions:
        return {"ok": False, "session": session, "text": "", "detail": "no-question", "pane": pane}
    if 1 <= qi <= len(questions) and questions[qi - 1].get("multiSelect"):
        return {"ok": False, "session": session, "text": "", "detail": "multi", "pane": pane}

    text = compose_answer(questions, f"{qi}:{oi}")
    if not text:
        return {"ok": False, "session": session, "text": "", "detail": "bad-option", "pane": pane}
    if pane in SHELL_COMMANDS:
        return {"ok": False, "session": session, "text": text, "detail": "shell", "pane": pane}
    return {"ok": True, "session": session, "text": text, "detail": "", "pane": pane}


def button_refusal(decision, sessions):
    """The DM to send when a tap must not be typed."""
    session = decision["session"]
    detail = decision["detail"]
    if detail == "no-session":
        live = ", ".join(sessions) or "none"
        return f"No session named `{session}`. Live sessions: {live}.\nNothing was sent."
    if detail == "shell":
        preview = decision["text"][:60]
        return (
            f"⚠️ [{session}] is at a `{decision['pane']}` prompt -- the agent is not "
            f"running, so this would have been executed as a shell command. "
            f"Nothing was sent.\n"
            f"To do it anyway: `!run {preview}`"
        )
    if detail == "multi":
        return f"[{session}] is a multi-select card -- reply `1:1,2`. Nothing was sent."
    if detail == "no-question":
        return f"[{session}] has no question waiting. Nothing was sent."
    return f"[{session}] that option is not on the card. Nothing was sent."


def compose_answer(questions, reply):
    """Turn "1:2,3 | 2:1 -- also keep it dark" into prose Claude understands.

    Returns None when the reply contains no picks at all, in which case the
    reply is sent through untouched as ordinary free text.
    """
    body, _, note = reply.partition("--")
    picks = PICK_RE.findall(body)
    if not picks:
        return None

    lines = []
    for q_raw, opts_raw in picks:
        qi = int(q_raw) - 1
        if not (0 <= qi < len(questions)):
            continue
        question = questions[qi]
        options = question.get("options") or []
        labels = []
        for o_raw in opts_raw.split(","):
            oi = int(o_raw.strip()) - 1
            if 0 <= oi < len(options):
                labels.append(options[oi].get("label", ""))
        if not labels:
            continue
        header = question.get("header") or question.get("question", f"Q{qi + 1}")
        lines.append(f"{header}: {', '.join(labels)}")

    if not lines:
        return None
    note = note.strip()
    if note:
        lines.append(f"Also: {note}")
    # Deliberately ONE line. A newline pasted into Claude Code's input box
    # arrives as a carriage return, so multi-line answers come out corrupted
    # ("...pageAlso: keep it minimal"). Verified against a real transcript.
    return "; ".join(lines)


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
    forced = False
    for pattern in TARGET_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        candidate, rest = m.group(1), m.group(2).strip()
        if candidate.lower() == "sessions":
            await message.channel.send(f"Live sessions: {', '.join(sessions) or 'none'}")
            return
        if candidate.lower() == "run":
            # "!run <command>" -- deliberately send this to a pane even if what
            # is sitting there is a shell. Restarting an agent that died while
            # you were out is the reason this exists.
            forced, text = True, rest
            break
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

    # "[api] !run <command>" -- the same escape hatch, after an explicit target.
    m = FORCE_RE.match(text)
    if m:
        forced, text = True, m.group(1).strip()

    # Refuse to type into a pane whose agent has exited. Without this, a reply
    # meant for a prompt is handed to whatever shell is sitting there and run as
    # a command: "yes" is harmless, "remove the temp files" is not.
    if not forced:
        running = pane_command(target)
        if running in SHELL_COMMANDS:
            append_audit({
                "session": target, "source": "dm", "action": "type", "text": text,
                "pane_command": running, "forced": False, "ok": False, "detail": "shell",
            })
            await message.channel.send(
                f"⚠️ [{target}] is at a `{running}` prompt -- the agent is not "
                f"running, so this would have been executed as a shell command. "
                f"Nothing was sent.\n"
                f"To do it anyway: `!run {text[:60]}`"
            )
            return

    note = ""
    pending = load_pending_question(target)

    # "pick 2" -- or a bare "2" while a prompt is actually on screen, which has
    # no other sensible reading once the options have been listed in the DM.
    # An AskUserQuestion card is left to the "1:2,3" path below: a digit into a
    # multi-select card has not been tested, and guessing is what this whole
    # area is trying to stop.
    chosen = None
    explicit = SELECT_CMD_RE.match(text)
    if explicit and pending:
        await message.channel.send(
            f"[{target}] is on a question card -- answer it with `1:2` "
            f"(question 1, option 2) rather than `pick`."
        )
        return
    if explicit:
        chosen = int(explicit.group(1))
    else:
        bare = BARE_NUMBER_RE.match(text)
        if bare and not pending and pane_has_selector(target):
            chosen = int(bare.group(1))

    if chosen is not None:
        ok, detail = choose_option(target, chosen)
        append_audit({
            "session": target, "source": "dm", "action": "pick", "text": str(chosen),
            "pane_command": pane_command(target), "forced": False, "ok": ok, "detail": detail,
        })
        if ok:
            await message.channel.send(f"✅ [{target}] chose **{chosen}. {detail}**")
        else:
            await message.channel.send(f"⚠️ [{target}] {detail}")
        return

    # If this session is sitting on an AskUserQuestion, translate picks like
    # "1:2,3" into the option labels Claude is expecting. A reply with no picks
    # in it passes through untouched as ordinary free text.
    if pending:
        composed = compose_answer(pending.get("questions") or [], text)
        if composed:
            text = composed
            note = " (answered the pending question)"
        clear_pending_question(target)

    # Dismiss any open selector before typing, or the paste would choose for you.
    # Read the options first: after dismissing they are gone, and knowing what
    # was on screen is what turns "it got dismissed" into something actionable.
    selector_open = pane_has_selector(target)
    dismissed_options = ""
    if selector_open and not pending:
        options, highlighted = pane_options(target)
        note = " (a prompt was open, so it was dismissed rather than answered)"
        if options:
            dismissed_options = ("\nIt was offering: " + format_options(options, highlighted)
                                 + "\nNext time reply `pick <n>` to choose one.")

    ok, err = type_into_session(target, text,
                                dismiss_first=bool(pending) or selector_open)
    append_audit({
        "session": target, "source": "dm", "action": "type", "text": text,
        "pane_command": pane_command(target), "forced": forced, "ok": ok, "detail": err,
    })
    if not ok:
        log.error("send to %s failed: %s", target, err)
        await message.channel.send(f"⚠️ failed to send to [{target}]: {err}")
        return
    await message.channel.send(f"↩️ sent to [{target}]{note}{dismissed_options}")


def frozen_view(message):
    """The same buttons, disabled, so a second tap cannot inject again."""
    view = discord.ui.View(timeout=None)
    for row in message.components:
        for child in getattr(row, "children", []):
            if not getattr(child, "custom_id", None):
                continue
            view.add_item(discord.ui.Button(
                label=(child.label or "option")[:80],
                custom_id=child.custom_id,
                style=child.style,
                disabled=True,
            ))
    return view


@client.event
async def on_interaction(interaction: discord.Interaction):
    """A tap on a question-card button. Same allowlist and typing path as a DM."""
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = (interaction.data or {}).get("custom_id") or ""
    if parse_button_id(custom_id) is None:
        return

    user = interaction.user
    if user is None or user.id != ALLOWED_USER_ID:
        log.warning("Ignored button from unauthorized user %s", getattr(user, "id", None))
        await interaction.response.send_message("Not allowed.")
        return

    await interaction.response.defer()
    sessions = tmux_sessions()
    name, _, _ = parse_button_id(custom_id)
    session = next((s for s in sessions if s.lower() == name.lower()), None)
    pane = pane_command(session) if session else ""
    pending = load_pending_question(session) if session else None
    decision = decide_button(custom_id, sessions, pending, pane)
    if not decision["ok"]:
        append_audit({
            "session": decision["session"], "source": "button", "action": "type",
            "text": decision["text"], "pane_command": decision["pane"], "forced": False,
            "ok": False, "detail": decision["detail"], "discord_id": str(interaction.id),
        })
        await interaction.followup.send(button_refusal(decision, sessions))
        return

    # Clear before typing so a second tap, already in flight, finds nothing
    # waiting and is refused. A failed type is recoverable from the keyboard.
    clear_pending_question(decision["session"])
    ok, err = type_into_session(decision["session"], decision["text"], dismiss_first=True)
    append_audit({
        "session": decision["session"], "source": "button", "action": "type",
        "text": decision["text"], "pane_command": pane, "forced": False,
        "ok": ok, "detail": err, "discord_id": str(interaction.id),
    })
    if not ok:
        log.error("button send to %s failed: %s", decision["session"], err)
        await interaction.followup.send(
            f"⚠️ failed to send to [{decision['session']}]: {err}"
        )
        return

    if interaction.message is not None:
        try:
            await interaction.message.edit(view=frozen_view(interaction.message))
        except Exception as e:
            log.warning("could not disable buttons: %s", e)
    await interaction.followup.send(
        f"↩️ sent to [{decision['session']}] (answered the pending question)"
    )


def main():
    global BOT_TOKEN, ALLOWED_USER_ID
    try:
        BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
        ALLOWED_USER_ID = int(os.environ["DISCORD_USER_ID"])
    except KeyError as e:
        sys.exit(f"bot: {e.args[0]} is not set -- check your .env")
    except ValueError:
        sys.exit("bot: DISCORD_USER_ID must be a number")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    client.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
