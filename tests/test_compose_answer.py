"""compose_answer turns a Discord reply like "1:2,3 -- also keep it dark"
into the prose that gets typed into Claude Code."""
import pytest

from bot import PICK_RE, compose_answer

QUESTIONS = [
    {"header": "Style", "question": "Which look?",
     "options": [{"label": "Minimal"}, {"label": "Dense"}, {"label": "Playful"}]},
    {"header": "Theme", "question": "Light or dark?", "multiSelect": False,
     "options": [{"label": "Light"}, {"label": "Dark"}]},
]


def test_single_pick():
    assert compose_answer(QUESTIONS, "1:1") == "Style: Minimal"


def test_dot_form_is_accepted():
    # The card prints codes as `1.2`, so people type them back that way.
    assert compose_answer(QUESTIONS, "1.2") == "Style: Dense"


def test_multi_select():
    assert compose_answer(QUESTIONS, "1:1,3") == "Style: Minimal, Playful"


def test_several_questions():
    assert compose_answer(QUESTIONS, "1:2 | 2:2") == "Style: Dense; Theme: Dark"


def test_free_note_after_dashes():
    out = compose_answer(QUESTIONS, "1:1 -- but keep the sidebar")
    assert out == "Style: Minimal; Also: but keep the sidebar"


def test_plain_prose_passes_through_untouched():
    # None means "send the reply as-is", which is what free text must do.
    assert compose_answer(QUESTIONS, "let me verify first") is None


def test_answer_is_always_one_line():
    """A newline pasted into Claude Code's input box arrives as a carriage
    return and corrupts the answer ("...pageAlso: keep it minimal"). This is
    the regression guard for that -- verified against a real transcript."""
    out = compose_answer(QUESTIONS, "1:1,2 | 2:1 -- and a longer note here")
    assert "\n" not in out and "\r" not in out


def test_out_of_range_question_is_ignored():
    assert compose_answer(QUESTIONS, "9:1") is None


def test_out_of_range_option_is_ignored():
    assert compose_answer(QUESTIONS, "1:99") is None


def test_partly_valid_picks_keep_the_valid_half():
    assert compose_answer(QUESTIONS, "1:1 | 9:1") == "Style: Minimal"


def test_header_falls_back_to_the_question_text():
    qs = [{"question": "Which look?", "options": [{"label": "Minimal"}]}]
    assert compose_answer(qs, "1:1") == "Which look?: Minimal"


@pytest.mark.parametrize("reply,expected", [
    ("1:1", [("1", "1")]),
    ("1 : 1", [("1", "1")]),
    ("1:1,2,3", [("1", "1,2,3")]),
    ("1:1 2:2", [("1", "1"), ("2", "2")]),
    ("no picks here", []),
])
def test_pick_regex(reply, expected):
    assert PICK_RE.findall(reply) == expected
