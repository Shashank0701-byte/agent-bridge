"""start_session.sh and the `claude` wrapper both derive the tmux session name
from the directory. If they ever disagree, one folder gets two sessions and
Discord replies go to the wrong agent -- so the shared function is pinned here.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "session_name.sh"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


def name_for(directory, session_name=None):
    override = f"SESSION_NAME={session_name!r} " if session_name is not None else ""
    script = f'. "{LIB}"; {override}agent_bridge_session_name "{directory}"'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("path,expected", [
    ("/home/me/promptwall", "promptwall"),
    ("/home/me/CodePulse", "CodePulse"),
    ("/home/me/my_api-v2", "my_api-v2"),
    ("/mnt/d/ClaudeProjects/agent-bridge", "agent-bridge"),
])
def test_plain_names_are_kept(path, expected):
    assert name_for(path) == expected


@pytest.mark.parametrize("path,expected", [
    ("/home/me/my.api", "my-api"),      # tmux splits targets on "."
    ("/home/me/a:b", "a-b"),            # ...and on ":"
])
def test_characters_tmux_treats_as_separators_become_dashes(path, expected):
    assert name_for(path) == expected


def test_everything_else_illegal_is_dropped():
    assert name_for("/home/me/my project (old)") == "myprojectold"


def test_an_explicit_override_wins():
    assert name_for("/home/me/promptwall", "api-v2") == "api-v2"


def test_the_name_never_contains_a_tmux_separator():
    for path in ("/a/b.c:d e", "/x/../weird.name", "/p/q:r.s"):
        out = name_for(path)
        assert "." not in out and ":" not in out and " " not in out
