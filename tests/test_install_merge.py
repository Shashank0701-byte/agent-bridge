"""install.sh merges our hooks into an existing ~/.claude/settings.json.

An earlier version used `jq -s '.[0] * .[1]'`, whose object merge replaces
arrays wholesale -- so installing the bridge silently deleted every hook the
user already had. These tests exist so that cannot come back.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXISTING = {
    "model": "opus",
    "hooks": {
        "Notification": [
            {"matcher": "permission_prompt",
             "hooks": [{"type": "command", "command": "/home/me/my-own-notifier.sh"}]}
        ],
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": "/home/me/audit-bash.sh"}]}
        ],
    },
}


@pytest.fixture
def home(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    (tmp_path / ".claude").mkdir()
    return tmp_path


def run_install(home):
    env = dict(os.environ, HOME=str(home))
    env.pop("USERPROFILE", None)
    r = subprocess.run(["bash", str(ROOT / "scripts" / "install.sh")],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    return json.loads((home / ".claude" / "settings.json").read_text())


def commands(settings, event):
    return [h.get("command", "")
            for entry in settings["hooks"].get(event, [])
            for h in entry.get("hooks", [])]


def test_hooks_are_added_to_an_empty_config(home):
    settings = run_install(home)
    assert any("notify.sh" in c for c in commands(settings, "Notification"))
    assert any("notify.sh" in c for c in commands(settings, "Stop"))
    assert any("ask_options.sh" in c for c in commands(settings, "PreToolUse"))


def test_existing_hooks_survive(home):
    (home / ".claude" / "settings.json").write_text(json.dumps(EXISTING))
    settings = run_install(home)
    assert "/home/me/my-own-notifier.sh" in commands(settings, "Notification")
    assert "/home/me/audit-bash.sh" in commands(settings, "PreToolUse")


def test_unrelated_settings_survive(home):
    (home / ".claude" / "settings.json").write_text(json.dumps(EXISTING))
    assert run_install(home)["model"] == "opus"


def test_rerunning_does_not_stack_up_duplicates(home):
    run_install(home)
    settings = run_install(home)
    ours = [c for c in commands(settings, "Notification") if "notify.sh" in c]
    assert len(ours) == 1


def test_the_placeholder_is_replaced_with_a_real_path(home):
    settings = run_install(home)
    every = (commands(settings, "Notification") + commands(settings, "Stop")
             + commands(settings, "PreToolUse"))
    assert every and not any("__AGENT_BRIDGE_DIR__" in c for c in every)
    assert all(Path(c.split()[0]).exists() for c in every)


def test_an_existing_config_is_backed_up_first(home):
    (home / ".claude" / "settings.json").write_text(json.dumps(EXISTING))
    run_install(home)
    backups = list((home / ".claude").glob("settings.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == EXISTING


def test_a_corrupt_config_is_refused_rather_than_overwritten(home):
    """Truncating someone's settings.json because it had a stray comma would be
    a much worse outcome than refusing to install."""
    broken = '{"hooks": {,,,'
    (home / ".claude" / "settings.json").write_text(broken)
    env = dict(os.environ, HOME=str(home))
    env.pop("USERPROFILE", None)
    r = subprocess.run(["bash", str(ROOT / "scripts" / "install.sh")],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode != 0
    assert (home / ".claude" / "settings.json").read_text() == broken
