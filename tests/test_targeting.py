"""How a DM is aimed at one of several live tmux sessions.

The "[name] text" form matters as much as "!name text": it mirrors the
notification being replied to, so it is the form people actually type. When it
was missing, a reply meant for one project was typed into another one.
"""
import pytest

from bot import SESSION_TAG_RE, TARGET_PATTERNS


def parse(text):
    """Whatever on_message's targeting loop would extract, or None."""
    for pattern in TARGET_PATTERNS:
        m = pattern.match(text)
        if m:
            return m.group(1), m.group(2).strip()
    return None


@pytest.mark.parametrize("text", [
    "!PromptWall yes",
    "[PromptWall] yes",
    "[PromptWall]yes",
    "! PromptWall yes",
    "[ PromptWall ] yes",
])
def test_both_targeting_forms(text):
    assert parse(text) == ("PromptWall", "yes")


def test_bare_target_with_no_body():
    assert parse("!PromptWall") == ("PromptWall", "")


def test_multiline_body_is_kept():
    # re.DOTALL: a pasted multi-line reply must not be truncated at the newline.
    assert parse("[api] line one\nline two") == ("api", "line one\nline two")


@pytest.mark.parametrize("text", [
    "just do it",
    "[see below] do it",      # a space means it is prose, not a session name
    "[10:30] standup notes",  # ":" is not legal in a tmux session name
    "yes",
])
def test_prose_is_not_mistaken_for_a_target(text):
    assert parse(text) is None


def test_session_names_allow_dashes_and_underscores():
    assert parse("[my_api-v2] go") == ("my_api-v2", "go")


def test_tag_is_recovered_from_a_bridge_message():
    """Replying to a notification is the main way to answer one, so the session
    name has to come back out of the text the bridge sent."""
    m = SESSION_TAG_RE.search("[PromptWall] Needs input: Continue with the plan?")
    assert m and m.group(1) == "PromptWall"


def test_tag_search_ignores_a_message_with_no_tag():
    assert SESSION_TAG_RE.search("Task finished") is None
