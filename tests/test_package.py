"""The installable command points hooks at the package, not at ~/agent-bridge."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_bridge.paths import hook_commands, project_root

ROOT = Path(__file__).resolve().parent.parent


def test_hook_commands_use_the_package_interpreter():
    root = Path("/opt/pipx/site-packages/agent_bridge/_bundle")
    python = "/opt/pipx/venvs/agent-bridge/bin/python"
    commands = hook_commands(root, python)
    recorded = " ".join(commands.values())
    assert python in recorded
    assert str(root / "hooks" / "notify.py") in commands["notify_input"]
    assert "~/agent-bridge" not in recorded


def test_a_checkout_is_the_project_root():
    assert project_root() == ROOT
    assert (project_root() / "scripts" / "bootstrap.sh").is_file()


@pytest.fixture
def home(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    (tmp_path / ".claude").mkdir()
    return tmp_path


def test_install_records_the_package_python_when_asked(home):
    seen = subprocess.run(
        ["bash", "-c", 'test -f "$1"', "bash", str(ROOT / "scripts" / "install.sh")],
        capture_output=True,
    )
    if seen.returncode != 0:
        pytest.skip("this bash cannot open a Windows path; the merge runs in CI")
    env = dict(os.environ, HOME=str(home), AGENT_BRIDGE_PYTHON=sys.executable)
    env.pop("USERPROFILE", None)
    r = subprocess.run(
        ["bash", str(ROOT / "scripts" / "install.sh")],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    commands = [
        hook.get("command", "")
        for entry in settings["hooks"].get("Notification", [])
        for hook in entry.get("hooks", [])
    ]
    assert commands
    assert all("~/agent-bridge" not in command for command in commands)
    assert any(sys.executable in command and "notify.py" in command for command in commands)
