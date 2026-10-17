"""get.sh installs a command. It does not clone into a directory of its own.

The interesting failures are still about the handover: no controlling terminal,
arguments passed through, and a truncated download that does no work.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GET_SH = ROOT / "scripts" / "get.sh"

pytestmark = pytest.mark.skipif(not shutil.which("sh"), reason="needs a POSIX sh")


@pytest.fixture
def fakes(tmp_path):
    """A pipx and an agent-bridge that record their arguments and succeed."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pipx_log = tmp_path / "pipx.txt"
    marker = tmp_path / "setup.txt"
    (bindir / "pipx").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" > "{pipx_log}"\n'
    )
    (bindir / "pipx").chmod(0o755)
    (bindir / "agent-bridge").write_text(
        "#!/bin/sh\n"
        f'{{ printf \'args=%s\\n\' "$*"; '
        f'if [ -t 0 ]; then echo stdin=tty; else echo stdin=not-a-tty; fi; }} > "{marker}"\n'
    )
    (bindir / "agent-bridge").chmod(0o755)
    return bindir, pipx_log, marker


def run_get(fakes, extra=(), repo=None, detached=True):
    bindir, pipx_log, marker = fakes
    env = dict(os.environ, PATH=str(bindir), GIT_TERMINAL_PROMPT="0")
    if repo is not None:
        env["AGENT_BRIDGE_REPO"] = str(repo)
    proc = subprocess.run(
        ["sh", str(GET_SH), *extra],
        env=env, capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL, start_new_session=detached,
    )
    return proc, pipx_log, marker


def test_it_installs_from_git_and_does_not_clone_into_home(fakes, tmp_path):
    sentinel = tmp_path / "home" / "agent-bridge"
    proc, pipx_log, marker = run_get(fakes)
    assert proc.returncode == 0, proc.stderr
    logged = pipx_log.read_text()
    assert logged.startswith("install --force git+")
    assert "gitlab.com/shashankchakraborty712005/agent-bridge.git@main" in logged
    assert not sentinel.exists()
    assert "stdin=not-a-tty" in marker.read_text()


def test_a_local_checkout_is_installed_as_itself(fakes, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    proc, pipx_log, _ = run_get(fakes, repo=checkout)
    assert proc.returncode == 0, proc.stderr
    assert pipx_log.read_text().strip() == f"install --force {checkout}"


def test_arguments_are_passed_through_to_setup(fakes):
    _, _, marker = run_get(fakes, extra=["--no-wrapper"])
    assert "args=setup --no-wrapper" in marker.read_text()


def test_running_it_again_just_reinstalls(fakes):
    assert run_get(fakes)[0].returncode == 0
    proc, pipx_log, _ = run_get(fakes)
    assert proc.returncode == 0, proc.stderr
    assert "install --force" in pipx_log.read_text()


def test_a_missing_pipx_and_uv_is_reported_with_a_way_to_fix_it(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    proc = subprocess.run(
        [shutil.which("sh"), str(GET_SH)],
        env={"PATH": str(empty), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode != 0
    assert "pipx or uv is required" in proc.stderr


@pytest.mark.parametrize("fraction", [0.25, 0.5, 0.6, 0.75, 0.9, 0.99])
def test_a_truncated_download_does_nothing_at_all(fraction, tmp_path):
    """Everything is inside main(), called on the last line, so half a file
    defines a function and stops rather than running half an installer."""
    head = GET_SH.read_text()[: int(len(GET_SH.read_text()) * fraction)]
    proc = subprocess.run(
        [shutil.which("sh"), "-c", head], capture_output=True, text=True,
        timeout=60, stdin=subprocess.DEVNULL,
        env=dict(os.environ, PATH=str(tmp_path), HOME=str(tmp_path)),
    )
    assert "==>" not in proc.stdout, "a truncated script started doing work"
