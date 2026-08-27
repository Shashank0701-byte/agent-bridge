#!/usr/bin/env python3
"""Outbound leg of the bridge: a hook fires, your phone buzzes.

Runs on Windows as well as Linux and macOS. That is the whole reason it is
Python rather than the shell script it replaces -- see hooks/lib/bridge.py for
why a .sh hook is actively dangerous on native Windows.

  notify.py input     the Notification hook: something needs you
  notify.py done      the Stop hook: it finished

Hook JSON arrives on stdin. Nothing here is allowed to take the session down,
so every failure path ends in a message on stderr and a zero exit -- except a
missing token, which is worth saying loudly because nothing will ever arrive.
"""
import json
import os
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

import bridge  # noqa: E402
import discord_send  # noqa: E402


def read_payload():
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def build_message(kind, session, payload):
    if kind == "done":
        return f"✅ [{session}] Task finished."

    reason = (payload.get("message") or payload.get("reason")
              or "Agent needs your input")
    text = f"\U0001f7e1 [{session}] Needs input: {reason}"

    # If a prompt is on screen, put its choices in the DM so it can be answered
    # rather than only acknowledged. Nothing to read on Windows: no tmux, no
    # pane, and inventing the options would be worse than omitting them.
    options = bridge.pane_options(session)
    if options:
        text += "\n" + "\n".join(options)
        text += "\nReply `pick <n>` to choose, or send text to dismiss it."
    return text


def main():
    bridge.load_env(HOOKS_DIR.parent)

    missing = [name for name in ("DISCORD_BOT_TOKEN", "DISCORD_USER_ID")
               if not os.environ.get(name)]
    if missing:
        print(f"notify: {', '.join(missing)} not set -- check your .env",
              file=sys.stderr)
        return 1

    kind = sys.argv[1] if len(sys.argv) > 1 else "input"
    payload = read_payload()
    session = bridge.session_name(payload)

    bridge.record_last_session(session)

    try:
        discord_send.send_dm(build_message(kind, session, payload))
    except Exception as e:                       # noqa: BLE001 - never block
        print(f"notify: could not send DM: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
