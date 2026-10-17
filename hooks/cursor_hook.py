#!/usr/bin/env python3
"""Cursor hook: a shell command or a finished turn becomes a Discord DM.

Cursor has no Notification event and does not load Claude's PermissionRequest
hook. beforeShellExecution is the moment a command has been proposed, which
is as close as the IDE gets to "blocked on you". stop is the task finishing.

The hook prints `{}` and exits 0. It must not return permission=allow: that
would approve the command. It must not return permission=ask either: the
phone is not the IDE's Run button, and holding the hook open until a DM
comes back would freeze the agent until Cursor's timeout.

  cursor_hook.py shell    beforeShellExecution
  cursor_hook.py stop     stop
"""
import json
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR / "lib"))

import bridge  # noqa: E402
import notify  # noqa: E402


def read_payload():
    if sys.stdin is None or getattr(sys.stdin, "isatty", lambda: False)():
        return {}
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def describe(event, payload):
    """(notify kind, message) or None when there is nothing worth a DM.

    The message is the whole DM body aside from the session tag notify adds.
    A shell event with no command is ignored: an empty proposal is not a
    question.
    """
    if event == "stop":
        status = (payload.get("status") or "completed").strip()
        return "done", f"Cursor agent {status}."

    command = (payload.get("command") or "").strip()
    if not command:
        return None
    if len(command) > 500:
        command = command[:499] + "…"
    return "input", (
        f"Cursor wants to run: {command}\n"
        "Approve or reject it in the Cursor window. A Discord reply is typed "
        "into a tmux session only — it does not press Run in the IDE."
    )


def main():
    bridge.load_env(HOOKS_DIR.parent)
    event = sys.argv[1] if len(sys.argv) > 1 else "shell"
    payload = read_payload()
    described = describe(event, payload)
    if described is not None:
        kind, reason = described
        session = bridge.session_name(payload)
        bridge.record_last_session(session)
        shaped = {"message": reason, "cwd": payload.get("cwd")}
        try:
            import discord_send
            discord_send.send_dm(notify.build_message(kind, session, shaped))
        except Exception as e:                       # noqa: BLE001
            print(f"cursor_hook: could not send DM: {e}", file=sys.stderr)
    # Observe only. No permission field, so this hook cannot approve or deny.
    json.dump({}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                           # noqa: BLE001
        print(f"cursor_hook: {e}", file=sys.stderr)
        json.dump({}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(0)
