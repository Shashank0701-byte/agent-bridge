"""The parts of a hook that are the same on every platform.

The shell hooks did this work in bash: source .env, ask tmux for the session
name, keep the state file. None of that survives the trip to Windows, where
there is no tmux and where `bash` on PATH is the WSL shim -- so a .sh hook would
run in a different operating system from the agent that fired it, with a
different view of the filesystem, and half-work in confusing ways.

Doing it in Python instead means one implementation for both. Standard library
only, on purpose: a hook has to run under whatever interpreter is on PATH, not
under the bridge's virtualenv.
"""
import json
import os
import shutil
import string
import subprocess
from pathlib import Path

# Matches scripts/lib/session_name.sh exactly. If the two ever disagree, one
# folder ends up with two session names and replies go to the wrong agent.
_KEEP = set(string.ascii_letters + string.digits + "_-")


def load_env(repo_dir):
    """Read the repo's .env into os.environ without overwriting what is set.

    Deliberately not python-dotenv: hooks must run with a bare interpreter.
    """
    env_file = Path(repo_dir) / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\r")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # A real environment variable wins, so a caller can override .env.
        os.environ.setdefault(key, value)


def sanitise_session_name(name):
    """Fold a folder name into something tmux can address and Discord can tag."""
    name = name.replace(".", "-").replace(":", "-")
    return "".join(ch for ch in name if ch in _KEEP)


def session_name(payload=None):
    """Which session is this, in the order the answers can be trusted.

    An explicit name beats tmux, tmux beats the directory, and the directory is
    what Windows always falls back to because it has no tmux at all.
    """
    explicit = os.environ.get("TMUX_SESSION_NAME")
    if explicit:
        return sanitise_session_name(explicit)

    if shutil.which("tmux"):
        try:
            out = subprocess.run(["tmux", "display-message", "-p", "#S"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return sanitise_session_name(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass

    # Claude Code puts the project directory in the hook payload; falling back
    # to getcwd() covers hooks fired from somewhere that does not.
    cwd = (payload or {}).get("cwd") or os.getcwd()
    name = sanitise_session_name(Path(cwd).name)
    return name or "unknown"


def state_file():
    raw = os.environ.get("AGENT_BRIDGE_STATE", "~/.agent-bridge/state.json")
    return Path(os.path.expanduser(raw))


def record_last_session(session):
    """Remember who pinged, so a reply with no target still lands somewhere."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            state = {}
    state["last_session"] = session
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass          # a notifier must never take the session down with it


def pane_options(session):
    """The numbered choices on screen, as lines, or [] if we cannot see them.

    Only tmux can show us the pane, so on Windows this is always empty and the
    DM simply arrives without the options -- which is the honest outcome rather
    than a guess about what is on screen.
    """
    if not shutil.which("tmux"):
        return []
    try:
        out = subprocess.run(["tmux", "capture-pane", "-t", session, "-p"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []

    tail = out.stdout.splitlines()[-15:]
    if not any(marker in "\n".join(tail) for marker in
               ("Enter to confirm", "Enter to select", "Esc to cancel")):
        return []

    lines = []
    for line in tail:
        stripped = line.strip()
        head = stripped.lstrip("❯> ").strip()
        if head[:1].isdigit() and "." in head[:3] and len(head) > 2:
            lines.append(stripped)
    return lines[:9]
