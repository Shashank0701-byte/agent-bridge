"""Format an AskUserQuestion payload for Discord and stash it for the bot.

Reads the PreToolUse JSON on stdin. Writes the questions to
<state_dir>/questions/<session>.json so bot.py can turn "1:2,3" back into real
option labels, then DMs a readable version of the card.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
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
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "AskUserQuestion":
        return 0
    questions = (payload.get("tool_input") or {}).get("questions") or []
    if not questions:
        return 0

    session = os.environ.get("AB_SESSION", "unknown")
    state_dir = os.environ.get("AB_STATE_DIR") or os.path.expanduser("~/.agent-bridge")
    qdir = os.path.join(state_dir, "questions")
    os.makedirs(qdir, exist_ok=True)

    # Stash so the bot can map "1:2" back to the option's real label.
    with open(os.path.join(qdir, f"{session}.json"), "w") as f:
        json.dump({"session": session,
                   "tool_use_id": payload.get("tool_use_id"),
                   "questions": questions}, f, indent=2)

    # Remember which session pinged last, same as notify.sh.
    state_file = os.path.join(state_dir, "state.json")
    state = {}
    if os.path.exists(state_file):
        try:
            state = json.load(open(state_file))
        except Exception:
            state = {}
    state["last_session"] = session
    with open(state_file, "w") as f:
        json.dump(state, f)

    discord_send.send_dm(build_message(session, questions))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ask_options: {e}", file=sys.stderr)
        sys.exit(0)          # never block the agent
