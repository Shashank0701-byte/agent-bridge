"""Drive a real tmux session and read back exactly what arrived.

This is the one thing in the bridge with no safe substitute for the real
program. `tmux send-keys <text>` puts the reply through tmux's own argument
parser, which mangles it three different ways -- a leading "-" is read as a
flag, a trailing ";" as a command separator, and a reply that happens to say
"Enter" is delivered as a keypress. type_into_session goes through a paste
buffer loaded from stdin instead, and these tests are what prove it.
"""
import shutil
import subprocess
import time
from uuid import uuid4

import pytest

import bot

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")


@pytest.fixture
def pane(tmp_path):
    """A live session whose shell appends every line it is sent to a file."""
    out = tmp_path / "typed.txt"
    session = "abtest-" + uuid4().hex[:8]
    reader = f'while IFS= read -r line; do printf "%s\n" "$line" >> "{out}"; done'
    subprocess.run(["tmux", "new-session", "-d", "-s", session, "bash", "-c", reader],
                   check=True, capture_output=True)
    for _ in range(50):                       # wait for the shell to reach `read`
        if subprocess.run(["tmux", "has-session", "-t", session],
                          capture_output=True).returncode == 0:
            break
        time.sleep(0.05)
    time.sleep(0.3)
    yield session, out
    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)


def send(pane, text, expect=1, timeout=8):
    session, out = pane
    ok, err = bot.type_into_session(session, text)
    assert ok, f"type_into_session failed: {err}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        lines = out.read_text().splitlines() if out.exists() else []
        if len(lines) >= expect:
            time.sleep(0.2)                   # let a stray extra line show up
            return out.read_text().splitlines()
        time.sleep(0.05)
    got = out.read_text() if out.exists() else "<no file>"
    raise AssertionError(f"expected {expect} line(s), got {got!r}")


@pytest.mark.parametrize("text", [
    "hello world",
    "-rf --force",                            # tmux#4408: read as a flag
    "do it;",                                 # tmux#1849: read as a separator
    "Enter",                                  # collides with a key name
    "Up Down Escape C-c",                     # so do these
    "text with \"quotes\" and $HOME and `backticks`",
    "1:2,3 -- keep it minimal",               # a real question-card reply
    "café ✓",
])
def test_the_reply_arrives_exactly_as_written(pane, text):
    assert send(pane, text) == [text]


def test_one_reply_produces_exactly_one_line(pane):
    """A trailing newline in the buffer submits on its own, and then the
    explicit Enter is a stray keypress that lands on whatever prompt appears
    next. It has silently answered a question that way before."""
    assert send(pane, "just one\n") == ["just one"]


def test_replies_arrive_in_order(pane):
    for i, text in enumerate(("first", "second", "third"), 1):
        assert send(pane, text, expect=i)[-1] == text


def test_a_long_reply_survives(pane):
    text = "x" * 900
    assert send(pane, text) == [text]


def test_sending_to_a_session_that_does_not_exist_fails_cleanly(pane):
    ok, err = bot.type_into_session("no-such-session-" + uuid4().hex[:6], "hi")
    assert not ok and err


def test_a_plain_pane_is_not_mistaken_for_a_selector(pane):
    session, _ = pane
    assert bot.pane_has_selector(session) is False


def test_an_open_selector_is_detected(tmp_path):
    """Claude Code's modal selectors ignore pasted text and treat Enter as
    "choose the highlighted option", so replying while one is open auto-approved
    a plan once. Detecting the footer is what stops that."""
    session = "absel-" + uuid4().hex[:8]
    footer = "Do you want to proceed?\n  1. Yes\n  2. No\nEnter to select . Esc to cancel"
    subprocess.run(["tmux", "new-session", "-d", "-s", session,
                    "bash", "-c", f'printf "{footer}\n"; sleep 30'],
                   check=True, capture_output=True)
    try:
        time.sleep(0.5)
        assert bot.pane_has_selector(session) is True
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
