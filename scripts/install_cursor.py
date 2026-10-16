#!/usr/bin/env python3
"""Wire Cursor's hooks at ~/.cursor/hooks.json.

    python scripts/install_cursor.py
    python scripts/install_cursor.py --uninstall

Re-running replaces this project's previous entries instead of stacking them.
Hooks you added yourself are left in place. The commands call python and
cursor_hook.py directly, never a .sh file: on Windows, bash is the WSL shim.
"""
import json
import os
import re
import sys
from pathlib import Path, PureWindowsPath

REPO = Path(__file__).resolve().parent.parent
MARKER = "cursor_hook.py"
EVENTS = ("beforeShellExecution", "stop")


def quote_part(part):
    return f'"{part}"' if " " in part else part


def hook_command(python, repo, event):
    if "\\" in repo or re.match(r"^[A-Za-z]:", repo):
        script = str(PureWindowsPath(repo) / "hooks" / "cursor_hook.py")
    else:
        script = str(Path(repo) / "hooks" / "cursor_hook.py")
    arg = "stop" if event == "stop" else "shell"
    return " ".join(quote_part(p) for p in (python, script, arg))


def merge_hooks(current, python, repo):
    """Add our two hooks. Previous agent-bridge entries are replaced."""
    current = dict(current or {})
    hooks = dict(current.get("hooks") or {})
    for event in EVENTS:
        kept = [entry for entry in (hooks.get(event) or [])
                if MARKER not in (entry.get("command") or "")]
        command = hook_command(python, repo, event)
        hooks[event] = kept + [{"command": command}]
    current["version"] = current.get("version") or 1
    current["hooks"] = hooks
    return current


def remove_hooks(current):
    current = dict(current or {})
    hooks = {}
    for event, entries in (current.get("hooks") or {}).items():
        kept = [entry for entry in entries
                if MARKER not in (entry.get("command") or "")]
        if kept:
            hooks[event] = kept
    current["hooks"] = hooks
    return current


def hooks_path():
    override = os.environ.get("AGENT_BRIDGE_CURSOR_HOOKS")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cursor" / "hooks.json"


def load_hooks(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"install_cursor: {path} is not valid JSON ({e}); fix it and re-run")


def write_hooks(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main():
    uninstall = "--uninstall" in sys.argv[1:]
    path = hooks_path()
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backed up existing hooks to {backup}")
    current = load_hooks(path)
    updated = remove_hooks(current) if uninstall else merge_hooks(
        current, sys.executable, REPO)
    write_hooks(path, updated)
    print(f"wrote {path}")
    if not uninstall:
        print("Cursor reloads hooks.json on its own. Open a project and let the")
        print("agent propose a shell command -- the DM says what it wants to run.")
        print("Approving still happens in the Cursor window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
