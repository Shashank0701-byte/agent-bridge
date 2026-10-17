"""Where an install keeps its files, and the hook command that points at them."""
import os
import sys
from pathlib import Path


def project_root():
    """The directory that contains scripts/bootstrap.sh.

    A checkout (and an editable install) has that directory next to this
    package. A wheel has a copy under agent_bridge/_bundle, because pip does
    not install loose scripts from the repo root.
    """
    override = os.environ.get("AGENT_BRIDGE_ROOT")
    if override:
        return Path(override).expanduser()

    here = Path(__file__).resolve()
    checkout = here.parent.parent
    if (checkout / "scripts" / "bootstrap.sh").is_file():
        return checkout

    bundled = here.parent / "_bundle"
    if (bundled / "scripts" / "bootstrap.sh").is_file():
        return bundled

    sys.exit("agent-bridge: installed files are missing. Reinstall the package.")


def _quote(part):
    text = str(part)
    return f'"{text}"' if " " in text else text


def hook_commands(root, python):
    """Commands written into Claude's settings. The interpreter is the one
    that has this install, not whatever `python` happens to be on PATH.
    """
    root = Path(root)
    notify = root / "hooks" / "notify.py"
    ask = root / "hooks" / "ask_options.py"
    interp = _quote(python)
    return {
        "notify_input": f"{interp} {_quote(notify)} input",
        "notify_done": f"{interp} {_quote(notify)} done",
        "ask": f"{interp} {_quote(ask)}",
    }
