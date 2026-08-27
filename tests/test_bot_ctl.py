"""Only one supervisor, however the race is timed.

`start`'s liveness check is not a mutex. The `claude` wrapper calls start on
every invocation and the Windows logon task starts it too, so on boot both can
pass that check in the same instant. Two bots on one token both receive every
DM and both type the reply into tmux.

These tests run supervisors against a throwaway HOME and a stub interpreter, so
nothing here talks to Discord or touches the real bridge.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOT_CTL = ROOT / "scripts" / "bot_ctl.sh"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


@pytest.fixture
def home(tmp_path):
    """A HOME with a stub 'venv python' that just sits there like the bot does."""
    venv = tmp_path / ".venvs" / "agent-bridge" / "bin"
    venv.mkdir(parents=True)
    python = venv / "python"
    python.write_text("#!/usr/bin/env bash\nexec sleep 300\n")
    python.chmod(0o755)
    (tmp_path / ".agent-bridge").mkdir()
    return tmp_path


def env_for(home):
    return dict(os.environ, HOME=str(home), AGENT_BRIDGE_LOG=str(home / "bot.log"))


def supervise(home):
    return subprocess.Popen(["bash", str(BOT_CTL), "supervise"],
                            env=env_for(home), start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ctl(home, *args):
    return subprocess.run(["bash", str(BOT_CTL), *args], env=env_for(home),
                          capture_output=True, text=True, timeout=60)


def alive(proc):
    return proc.poll() is None


def stop_all(procs):
    for p in procs:
        if alive(p):
            p.kill()
            p.wait(timeout=10)


def test_two_supervisors_started_at_once_leave_exactly_one(home):
    """The actual boot race: nothing staggers these two."""
    procs = [supervise(home), supervise(home)]
    try:
        time.sleep(3)
        assert sum(alive(p) for p in procs) == 1, "both supervisors survived"
    finally:
        stop_all(procs)


def test_a_crowd_of_supervisors_still_leaves_exactly_one(home):
    procs = [supervise(home) for _ in range(6)]
    try:
        time.sleep(4)
        assert sum(alive(p) for p in procs) == 1
    finally:
        stop_all(procs)


def test_the_pid_file_names_the_survivor(home):
    procs = [supervise(home), supervise(home)]
    try:
        time.sleep(3)
        survivor = next(p for p in procs if alive(p))
        assert (home / ".agent-bridge" / "bot.pid").read_text().strip() == str(survivor.pid)
    finally:
        stop_all(procs)


def test_a_loser_exiting_does_not_delete_the_winners_pid_file(home):
    """The old EXIT trap removed the pid file unconditionally, so the loser
    took the winner's bookkeeping with it and `stop` then found nothing."""
    procs = [supervise(home), supervise(home)]
    try:
        time.sleep(3)
        pidfile = home / ".agent-bridge" / "bot.pid"
        assert pidfile.exists()
        for p in procs:
            if not alive(p):
                p.wait(timeout=10)          # the loser is already gone
        assert pidfile.exists(), "the loser deleted the winner's pid file"
        assert ctl(home, "status").stdout.startswith("running")
    finally:
        stop_all(procs)


def test_a_supervisor_that_exits_cleanly_frees_the_lock(home):
    first = supervise(home)
    time.sleep(2)
    first.terminate()
    first.wait(timeout=10)
    second = supervise(home)
    try:
        time.sleep(2)
        assert alive(second), "the lock outlived its owner"
    finally:
        stop_all([second])


def test_a_lock_left_behind_by_a_kill_9_does_not_wedge_the_bridge(home):
    """A reboot or a SIGKILL leaves the lock directory on disk with a pid in it
    that no longer exists. If that jammed the lock, the bridge would never start
    again -- and the user's only clue would be silence."""
    first = supervise(home)
    time.sleep(2)
    first.kill()
    first.wait(timeout=10)
    assert (home / ".agent-bridge" / "supervisor.lock").exists()   # stale, on purpose

    second = supervise(home)
    try:
        time.sleep(2)
        assert alive(second), "a stale lock blocked a legitimate start"
    finally:
        stop_all([second])


def test_a_lock_held_by_a_live_process_is_never_stolen(home):
    """The staleness check must key off the holder actually being dead."""
    first = supervise(home)
    try:
        time.sleep(2)
        lock_pid = (home / ".agent-bridge" / "supervisor.lock" / "pid").read_text().strip()
        second = supervise(home)
        second.wait(timeout=20)
        assert (home / ".agent-bridge" / "supervisor.lock" / "pid").read_text().strip() == lock_pid
    finally:
        stop_all([first])


def test_stop_then_start_works(home):
    assert ctl(home, "start").returncode == 0
    try:
        assert ctl(home, "status").stdout.startswith("running")
        assert ctl(home, "stop").returncode == 0
        assert ctl(home, "status").stdout.startswith("not running")
        assert ctl(home, "start").returncode == 0
        assert ctl(home, "status").stdout.startswith("running")
    finally:
        ctl(home, "stop")


def test_start_is_idempotent(home):
    assert ctl(home, "start").returncode == 0
    try:
        second = ctl(home, "start")
        assert second.returncode == 0
        assert "already running" in second.stdout
    finally:
        ctl(home, "stop")
