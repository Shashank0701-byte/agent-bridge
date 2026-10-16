"""Question-card buttons are a second way to send the same answer as `1:1`.

A tap that cannot represent the whole card must not exist: multi-select,
several questions, or a session name too long for Discord's custom_id all
fall back to the text reply.
"""
import json

from ask_options import build_message, button_custom_id, question_components
from discord_send import message_payloads

from bot import append_audit, decide_button

ONE = [
    {"header": "Style", "question": "Which look?", "multiSelect": False,
     "options": [{"label": "Minimal", "description": "less chrome"},
                 {"label": "Dense"}]},
]


def test_one_single_select_question_gets_one_button_per_option():
    rows = question_components("PromptWall", ONE)
    assert rows is not None
    buttons = rows[0]["components"]
    assert [b["label"] for b in buttons] == ["Minimal", "Dense"]
    assert buttons[0]["custom_id"] == "ab:q:PromptWall:1:1"
    assert buttons[1]["custom_id"] == button_custom_id("PromptWall", 1, 2)


def test_the_card_still_shows_the_text_reply():
    out = build_message("PromptWall", ONE, buttons=True)
    assert "Tap a button" in out
    assert "`1:1`" in out


def test_several_questions_stay_text_only():
    questions = ONE + [
        {"header": "Scope", "question": "How far?", "multiSelect": False,
         "options": [{"label": "Now"}]},
    ]
    assert question_components("s", questions) is None


def test_multi_select_stays_text_only():
    questions = [{
        "header": "Scope", "multiSelect": True,
        "options": [{"label": "Now"}, {"label": "Later"}],
    }]
    assert question_components("s", questions) is None


def test_more_than_five_options_stay_text_only():
    options = [{"label": f"Opt {i}"} for i in range(1, 7)]
    questions = [{"header": "Many", "options": options}]
    assert question_components("s", questions) is None


def test_a_custom_id_that_would_not_fit_stays_text_only():
    # "ab:q:" + session + ":1:1" must stay within Discord's 100-character custom_id.
    assert question_components("x" * 95, ONE) is None


def test_a_long_label_is_truncated_to_the_button_limit():
    questions = [{"header": "H", "options": [{"label": "L" * 100}]}]
    label = question_components("s", questions)[0]["components"][0]["label"]
    assert len(label) == 80
    assert label.endswith("…")


def test_a_tap_becomes_the_same_prose_as_a_typed_pick():
    pending = {"questions": ONE}
    decision = decide_button("ab:q:PromptWall:1:2", ["PromptWall"], pending, "claude")
    assert decision["ok"] is True
    assert decision["text"] == "Style: Dense"


def test_a_tap_for_a_dead_session_sends_nothing():
    pending = {"questions": ONE}
    decision = decide_button("ab:q:gone:1:1", ["PromptWall"], pending, "")
    assert decision["ok"] is False
    assert decision["detail"] == "no-session"
    assert decision["text"] == ""


def test_a_tap_into_a_shell_is_refused_with_the_answer_it_would_have_typed():
    pending = {"questions": ONE}
    decision = decide_button("ab:q:PromptWall:1:1", ["PromptWall"], pending, "bash")
    assert decision["ok"] is False
    assert decision["detail"] == "shell"
    assert decision["text"] == "Style: Minimal"


def test_a_tap_with_no_question_waiting_is_refused():
    decision = decide_button("ab:q:PromptWall:1:1", ["PromptWall"], None, "claude")
    assert decision == {
        "ok": False, "session": "PromptWall", "text": "", "detail": "no-question", "pane": "claude",
    }


def test_components_ride_on_the_last_chunk_only():
    text = "\n".join("y" * 100 for _ in range(40))
    rows = question_components("s", ONE)
    payloads = message_payloads(text, rows)
    assert len(payloads) > 1
    assert "components" not in payloads[0]
    assert payloads[-1]["components"] == rows


def test_audit_appends_one_json_line(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AGENT_BRIDGE_AUDIT", str(path))
    append_audit({
        "session": "PromptWall", "source": "button", "action": "type",
        "text": "Style: Minimal", "pane_command": "", "forced": False,
        "ok": False, "detail": "no-session",
    })
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line["session"] == "PromptWall"
    assert line["ok"] is False
    assert line["detail"] == "no-session"
    assert line["ts"].endswith("Z")
