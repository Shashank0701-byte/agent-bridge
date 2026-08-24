"""The Discord card built from an AskUserQuestion payload.

The codes it prints (`1.2`) have to be the codes compose_answer accepts, or
picking an option silently does nothing.
"""
from ask_options import build_message

from bot import PICK_RE, compose_answer

PAYLOAD = [
    {"header": "Style", "question": "Which look?", "multiSelect": False,
     "options": [{"label": "Minimal", "description": "less chrome"},
                 {"label": "Dense", "description": "more per screen"}]},
    {"header": "Scope", "question": "How far?", "multiSelect": True,
     "options": [{"label": "Now"}, {"label": "Later"}]},
]


def test_card_lists_every_option_with_a_code():
    out = build_message("PromptWall", PAYLOAD)
    for code in ("1.1", "1.2", "2.1", "2.2"):
        assert f"`{code}`" in out


def test_card_names_the_session():
    assert "[PromptWall]" in build_message("PromptWall", PAYLOAD)


def test_multi_select_is_advertised_differently():
    out = build_message("s", PAYLOAD)
    assert "pick one" in out and "pick any" in out


def test_descriptions_are_shown_when_present():
    assert "less chrome" in build_message("s", PAYLOAD)


def test_missing_options_and_descriptions_do_not_crash():
    build_message("s", [{"header": "Bare", "question": "?"}])


def test_the_example_reply_the_card_suggests_actually_parses():
    """The card ends with "Reply with your picks, e.g. `1:1 | 2:1`". If that
    example does not survive the parser, every first-time user is misled."""
    out = build_message("s", PAYLOAD)
    example = next(line for line in out.splitlines() if "e.g." in line)
    suggestion = example.split("`")[1]
    assert PICK_RE.findall(suggestion)
    assert compose_answer(PAYLOAD, suggestion) == "Style: Minimal; Scope: Now"
