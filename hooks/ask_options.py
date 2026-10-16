#!/usr/bin/env python3
"""Format an AskUserQuestion payload for Discord and stash it for the bot.

Reads the PreToolUse JSON on stdin. Writes the questions to
<state_dir>/questions/<session>.json so bot.py can turn "1:2,3" back into real
option labels, then DMs a readable version of the card.

Runs standalone on any platform: it loads .env and works out the session name
itself rather than being handed them by a shell wrapper, because on native
Windows there is no shell wrapper that can be trusted to do it.
"""
import json
import os
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

import bridge  # noqa: E402
import discord_send  # noqa: E402

# Discord: 5 buttons on a row, 80 characters on a label, 100 on a custom_id.
# A tap has to answer the whole card, so buttons exist only for one
# single-select question. Multi-select and multi-question cards stay text.
MAX_BUTTONS = 5
LABEL_LIMIT = 80
ID_LIMIT = 100


def button_custom_id(session, question, option):
    """Id the bot parses back into a session and a 1-based pick."""
    return f"ab:q:{session}:{question}:{option}"


def question_components(session, questions):
    """Action row for a one-question single-select card, or None.

    None means "send the text card only". A card we cannot represent as one
    tap must not grow a button that would answer half of it.
    """
    if len(questions) != 1 or questions[0].get("multiSelect"):
        return None
    options = questions[0].get("options") or []
    if not 1 <= len(options) <= MAX_BUTTONS:
        return None

    buttons = []
    for oi, opt in enumerate(options, 1):
        label = (opt.get("label") or "").strip()
        if not label:
            return None
        custom_id = button_custom_id(session, 1, oi)
        if len(custom_id) > ID_LIMIT:
            return None
        if len(label) > LABEL_LIMIT:
            label = label[:LABEL_LIMIT - 1] + "…"
        buttons.append({
            "type": 2,          # button
            "style": 1,         # primary
            "label": label,
            "custom_id": custom_id,
        })
    return [{"type": 1, "components": buttons}]


def build_message(session, questions, buttons=False):
    lines = [f"\U0001f7e1 **[{session}]** needs a decision "
             f"({len(questions)} question{'s' if len(questions) != 1 else ''})", ""]
    for qi, q in enumerate(questions, 1):
        how = "pick any" if q.get("multiSelect") else "pick one"
        header = q.get("header") or f"Question {qi}"
        lines.append(f"**{qi}. {header}** _({how})_")
        lines.append(q.get("question", ""))
        for oi, opt in enumerate(q.get("options") or [], 1):
            label = opt.get("label", "?")
            desc = (opt.get("description") or "").strip()
            lines.append(f"  `{qi}.{oi}` **{label}**" + (f" — {desc}" if desc else ""))
        lines.append("")
    example = " | ".join(f"{i}:1" for i in range(1, len(questions) + 1))
    if buttons:
        lines.append(f"Tap a button, or reply with your picks, e.g. `{example}`")
    else:
        lines.append(f"Reply with your picks, e.g. `{example}`")
    lines.append("Add a note after `--` to say anything else, or just reply in plain words.")
    return "\n".join(lines)


def main():
    bridge.load_env(HOOKS_DIR.parent)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "AskUserQuestion":
        return 0
    questions = (payload.get("tool_input") or {}).get("questions") or []
    if not questions:
        return 0

    # AB_SESSION is honoured first so a settings.json from an older install,
    # which sets it in the shell wrapper, keeps behaving the same.
    session = os.environ.get("AB_SESSION") or bridge.session_name(payload)
    state_dir = Path(os.environ.get("AB_STATE_DIR")
                     or bridge.state_file().parent)
    qdir = state_dir / "questions"
    qdir.mkdir(parents=True, exist_ok=True)

    # Stash so the bot can map "1:2" back to the option's real label.
    (qdir / f"{session}.json").write_text(
        json.dumps({"session": session,
                    "tool_use_id": payload.get("tool_use_id"),
                    "questions": questions}, indent=2),
        encoding="utf-8")

    bridge.record_last_session(session)
    components = question_components(session, questions)
    discord_send.send_dm(
        build_message(session, questions, buttons=bool(components)),
        components,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ask_options: {e}", file=sys.stderr)
        sys.exit(0)          # never block the agent
