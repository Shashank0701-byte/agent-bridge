"""The one-command installer, run offline against a local origin.

get.sh's job is to clone and then hand over to bootstrap.sh, which means the
interesting failures are all about the handover rather than the cloning. In
particular it must survive having no controlling terminal: that is every
container, cron job and `ssh host '... | sh'`, and it is where `[ -r /dev/tty ]`
lies -- access() answers yes and the open then fails with ENXIO.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GET_SH = ROOT / "scripts" / "get.sh"

pytestmark = pytest.mark.skipif(
    not shutil.which("git") or not shutil.which("sh"),
    reason="needs git and a POSIX sh",
)


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def origin(tmp_path):
    """A bare repo holding a stub bootstrap.sh that records how it was called."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)],
                   check=True, capture_output=True)

    work = tmp_path / "work"
    (work / "scripts").mkdir(parents=True)
    marker = tmp_path / "bootstrap-ran.txt"
    (work / "scripts" / "bootstrap.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'{{ echo "args=$*"; if [ -t 0 ]; then echo "stdin=tty"; '
        f'else echo "stdin=not-a-tty"; fi; }} > "{marker}"\n'
    )
    (work / "scripts" / "bootstrap.sh").chmod(0o755)

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)],
                   check=True, capture_output=True)
    git("config", "user.email", "t@t", cwd=work)
    git("config", "user.name", "t", cwd=work)
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "stub", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "--quiet", "origin", "main", cwd=work)
    return bare, marker


def run_get(origin, target, detached, extra=()):
    """Run get.sh. `detached` gives it no controlling terminal, like a container."""
    bare, marker = origin
    env = dict(os.environ,
               AGENT_BRIDGE_REPO=str(bare),
               AGENT_BRIDGE_REF="main",
               AGENT_BRIDGE_DIR=str(target),
               GIT_TERMINAL_PROMPT="0")
    proc = subprocess.run(
        ["sh", str(GET_SH), *extra],
        env=env, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL, start_new_session=detached,
    )
    return proc, marker


def test_it_installs_with_no_controlling_terminal(origin, tmp_path):
    """The case CI and cron are in. `[ -r /dev/tty ]` says the device is
    readable here and opening it fails, which killed the whole install."""
    proc, marker = run_get(origin, tmp_path / "target", detached=True)
    assert proc.returncode == 0, proc.stderr
    assert marker.exists(), "bootstrap.sh was never reached"
    assert "stdin=not-a-tty" in marker.read_text()


def test_the_clone_lands_where_it_was_told(origin, tmp_path):
    target = tmp_path / "target"
    proc, _ = run_get(origin, target, detached=True)
    assert proc.returncode == 0
    assert (target / ".git").is_dir()
    assert (target / "scripts" / "bootstrap.sh").exists()


def test_arguments_are_passed_through_to_bootstrap(origin, tmp_path):
    _, marker = run_get(origin, tmp_path / "target", detached=True,
                        extra=["--no-wrapper"])
    assert "args=--no-wrapper" in marker.read_text()


def test_running_it_again_updates_in_place(origin, tmp_path):
    target = tmp_path / "target"
    assert run_get(origin, target, detached=True)[0].returncode == 0
    proc, marker = run_get(origin, target, detached=True)
    assert proc.returncode == 0, proc.stderr
    assert marker.exists()


def test_a_directory_it_did_not_create_is_left_alone(origin, tmp_path):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "mine.txt").write_text("do not delete me")
    proc, _ = run_get(origin, occupied, detached=True)
    assert proc.returncode != 0
    assert "already exists" in proc.stderr
    assert (occupied / "mine.txt").read_text() == "do not delete me"


def test_a_missing_git_is_reported_with_a_way_to_fix_it(origin, tmp_path):
    """Someone running this on a fresh machine is exactly who hits it."""
    bare, _ = origin
    empty = tmp_path / "nothing"
    empty.mkdir()
    # An absolute path for sh itself: the empty PATH is meant to hide git from
    # the script, not hide the interpreter from Python.
    proc = subprocess.run(
        [shutil.which("sh"), str(GET_SH)],
        env={"PATH": str(empty), "HOME": str(tmp_path),
             "AGENT_BRIDGE_REPO": str(bare), "AGENT_BRIDGE_DIR": str(tmp_path / "t")},
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode != 0
    assert "git is required" in proc.stderr


@pytest.mark.parametrize("fraction", [0.25, 0.5, 0.6, 0.75, 0.9, 0.99])
def test_a_truncated_download_does_nothing_at_all(fraction, tmp_path):
    """Everything is inside main(), called on the last line, so half a file
    defines a function and stops rather than running half an installer.

    What matters is that it takes no action -- a syntax error from a cut that
    lands mid-block is a perfectly good way to take no action, so the exit code
    is not the thing to assert on.
    """
    head = GET_SH.read_text()[: int(len(GET_SH.read_text()) * fraction)]
    target = tmp_path / "should-not-appear"
    proc = subprocess.run(
        [shutil.which("sh"), "-c", head], capture_output=True, text=True,
        timeout=60, stdin=subprocess.DEVNULL,
        env=dict(os.environ, AGENT_BRIDGE_DIR=str(target)),
    )
    assert "==>" not in proc.stdout, "a truncated script started doing work"
    assert not target.exists(), "a truncated script created the install directory"
