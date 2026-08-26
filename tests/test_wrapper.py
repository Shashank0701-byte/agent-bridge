"""The transparent `claude` wrapper.

Its whole job is to add things -- the bot, a tmux session, and now --continue --
without changing what you asked for. These tests pin the parts that are easy to
get subtly wrong: not doubling a flag you passed yourself, and not touching a
non-interactive invocation at all.

The wrapper checks for a terminal before it does anything, so every case runs
under a pty. TMUX is set so it takes the "already inside tmux" branch and execs
the stub directly, which keeps real tmux out of the tests.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "claude-wrapper.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"),
    reason="needs a pty and bash",
)


@pytest.fixture
def wrapper(tmp_path):
    """A rendered wrapper whose `claude` and bot_ctl.sh are recording stubs."""
    args_file = tmp_path / "args.txt"
    bot_marker = tmp_path / "bot_ctl_was_called"

    # A loop rather than printf "%s\n" "$@": with zero arguments printf still
    # emits one empty line, which reads back as an argument nobody passed.
    real = tmp_path / "claude-real"
    real.write_text(
        "#!/usr/bin/env bash\n"
        f': > "{args_file}"\n'
        f'for a in "$@"; do printf "%s\\n" "$a" >> "{args_file}"; done\n'
    )
    real.chmod(0o755)

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    bot_ctl = repo / "scripts" / "bot_ctl.sh"
    bot_ctl.write_text("#!/usr/bin/env bash\n" f'touch "{bot_marker}"\n')
    bot_ctl.chmod(0o755)

    path = tmp_path / "claude"
    path.write_text(
        TEMPLATE.read_text()
        .replace("__AGENT_BRIDGE_DIR__", str(repo))
        .replace("__REAL_CLAUDE__", str(real))
    )
    path.chmod(0o755)
    return path, args_file, bot_marker


def run(wrapper, argv, **env_overrides):
    """Run the wrapper attached to a pty; return the args the real binary saw."""
    import pty

    path, args_file, bot_marker = wrapper
    env = dict(os.environ, TMUX="fake-tmux-socket,0,0")
    env.pop("AGENT_BRIDGE_RESUME", None)
    env.pop("AGENT_BRIDGE_WRAP", None)
    env.update({k: str(v) for k, v in env_overrides.items()})

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen([str(path), *argv], stdin=slave, stdout=slave,
                                stderr=slave, env=env, close_fds=True)
        os.close(slave)
        assert proc.wait(timeout=20) == 0
    finally:
        os.close(master)

    seen = args_file.read_text().splitlines() if args_file.exists() else []
    return seen, bot_marker.exists()


def test_a_bare_claude_continues_this_folders_conversation(wrapper):
    seen, _ = run(wrapper, [])
    assert seen == ["--continue"]


def test_the_bridge_is_started_on_the_way_through(wrapper):
    _, bot_started = run(wrapper, [])
    assert bot_started


@pytest.mark.parametrize("flag", ["-c", "--continue", "-r", "--resume",
                                  "--from-pr", "--cloud", "--bg", "--background"])
def test_a_conversation_flag_you_passed_is_not_doubled(wrapper, flag):
    """Passing --resume yourself and getting `--continue --resume` back would
    be the wrapper overriding an explicit choice."""
    seen, _ = run(wrapper, [flag])
    assert seen == [flag]


def test_resume_can_be_turned_off_for_one_run(wrapper):
    seen, _ = run(wrapper, [], AGENT_BRIDGE_RESUME="0")
    assert seen == []


def test_your_own_arguments_survive_intact(wrapper):
    seen, _ = run(wrapper, ["--model", "opus", "fix the flaky test"])
    assert seen == ["--continue", "--model", "opus", "fix the flaky test"]


def test_opting_out_of_the_wrapper_skips_resume_too(wrapper):
    seen, bot_started = run(wrapper, ["hello"], AGENT_BRIDGE_WRAP="0")
    assert seen == ["hello"]
    assert not bot_started


def test_headless_runs_are_left_completely_alone(wrapper):
    """-p is scripted use: no tmux, no bot, and no conversation of ours."""
    seen, bot_started = run(wrapper, ["-p", "say hi"])
    assert seen == ["-p", "say hi"]
    assert not bot_started


def test_a_missing_real_binary_fails_loudly(tmp_path):
    path = tmp_path / "claude"
    path.write_text(
        TEMPLATE.read_text()
        .replace("__AGENT_BRIDGE_DIR__", str(tmp_path))
        .replace("__REAL_CLAUDE__", str(tmp_path / "does-not-exist"))
    )
    path.chmod(0o755)
    r = subprocess.run([str(path)], capture_output=True, text=True)
    assert r.returncode != 0 and "real binary missing" in r.stderr
