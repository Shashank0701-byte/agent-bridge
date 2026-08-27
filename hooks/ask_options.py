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


def build_message(session, questions):
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
    lines += [
        "Reply with your picks, e.g. `" +
        " | ".join(f"{i}:1" for i in range(1, len(questions) + 1)) + "`",
        "Add a note after `--` to say anything else, or just reply in plain words.",
    ]
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
    discord_send.send_dm(build_message(session, questions))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ask_options: {e}", file=sys.stderr)
        sys.exit(0)          # never block the agent
