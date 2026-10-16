"""A start-session name has to become the real binary, not a guess."""
from agents import resolve


def test_claude_is_the_default():
    got = resolve("")
    assert got["id"] == "claude"
    assert got["command"] == "claude"
    assert got["prompt_regex"] is None


def test_cursor_launches_the_cli_named_agent():
    got = resolve("cursor")
    assert got["command"] == "agent"
    assert got["hooks"] == "cursor"
    assert got["prompt_regex"]


def test_extra_words_are_arguments_to_the_real_binary():
    assert resolve("cursor --mode ask")["command"] == "agent --mode ask"


def test_codex_and_gemini_are_watched():
    for name in ("codex", "gemini"):
        got = resolve(name)
        assert got["command"] == name
        assert got["hooks"] is None
        assert got["prompt_regex"]


def test_an_unknown_command_is_not_polled():
    got = resolve("python app.py")
    assert got["id"] is None
    assert got["command"] == "python app.py"
    assert got["prompt_regex"] is None
