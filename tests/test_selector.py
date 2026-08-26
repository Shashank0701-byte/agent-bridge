"""Reading and answering a modal selector.

The parsing half only. How the widget consumes keystrokes cannot be tested
against a fake pane -- that mapping was measured against a live Claude Code
2.1.241 and is recorded in bot.py, with the pane-driven half of these checks in
test_tmux_integration.py.
"""
import pytest

from bot import BARE_NUMBER_RE, OPTION_RE, SELECT_CMD_RE, format_options

TRUST_PROMPT = """\
 Quick safety check: Is this a project you created or one you trust?
 Security guide
 ❯ 1. Yes, I trust this folder
   2. No, exit
 Enter to confirm · Esc to cancel"""


def parse(pane):
    options, highlighted = [], None
    for line in pane.splitlines():
        m = OPTION_RE.match(line)
        if not m:
            continue
        number = int(m.group("number"))
        options.append((number, m.group("label")))
        if m.group("marker"):
            highlighted = number
    return options, highlighted


def test_a_real_trust_prompt_is_read_correctly():
    options, highlighted = parse(TRUST_PROMPT)
    assert options == [(1, "Yes, I trust this folder"), (2, "No, exit")]
    assert highlighted == 1


def test_the_marker_identifies_which_option_is_highlighted():
    moved = TRUST_PROMPT.replace(" ❯ 1.", "   1.").replace("   2.", " ❯ 2.")
    _, highlighted = parse(moved)
    assert highlighted == 2


def test_prose_is_not_mistaken_for_an_option():
    pane = "I looked at 3 files.\nSee section 2. It explains why.\nnothing here"
    assert parse(pane) == ([], None)


def test_an_option_label_keeps_its_punctuation():
    options, _ = parse(" ❯ 1. Yes, and don't ask again for `ls` commands")
    assert options == [(1, "Yes, and don't ask again for `ls` commands")]


@pytest.mark.parametrize("text,number", [
    ("pick 1", 1),
    ("pick 9", 9),
    ("!pick 2", 2),
    ("PICK 3", 3),
    ("pick  4", 4),
])
def test_the_pick_command_is_recognised(text, number):
    m = SELECT_CMD_RE.match(text)
    assert m and int(m.group(1)) == number


@pytest.mark.parametrize("text", [
    "pick",
    "pick one",
    "pick 1 please",
    "I pick 1",
    "picked 1",
])
def test_something_that_is_not_a_pick_command_is_left_alone(text):
    assert SELECT_CMD_RE.match(text) is None


@pytest.mark.parametrize("text", ["1", "2", "10"])
def test_a_bare_number_is_recognised(text):
    assert BARE_NUMBER_RE.match(text)


@pytest.mark.parametrize("text", ["1 yes", "yes 1", "1.", "1:2", "", "no"])
def test_anything_with_other_words_in_it_is_not_a_bare_number(text):
    """"1:2" in particular must stay with the question-card path, and "1 yes"
    is prose -- treating either as a keystroke would be guessing."""
    assert BARE_NUMBER_RE.match(text) is None


def test_the_options_line_marks_the_highlighted_one():
    out = format_options([(1, "Yes"), (2, "No")], 1)
    assert "**1. Yes**" in out and "2. No" in out and "**2." not in out


def test_the_options_line_survives_nothing_being_highlighted():
    out = format_options([(1, "Yes"), (2, "No")], None)
    assert "1. Yes" in out and "2. No" in out and "**" not in out
