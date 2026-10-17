"""The Cursor hook reports a proposed command and does not approve it."""
import json

from cursor_hook import describe, main


def test_a_shell_proposal_names_the_command():
    kind, text = describe("shell", {"command": "npm test", "cwd": "/work/app"})
    assert kind == "input"
    assert "npm test" in text
    assert "does not press Run" in text


def test_a_long_command_is_cut_off():
    _, text = describe("shell", {"command": "x" * 800})
    assert "x" * 499 in text
    assert "x" * 500 not in text.split("wants to run: ", 1)[1].split("\n", 1)[0]


def test_an_empty_proposal_is_not_a_question():
    assert describe("shell", {"command": "   "}) is None


def test_stop_is_a_finished_task():
    kind, text = describe("stop", {"status": "completed"})
    assert kind == "done"
    assert "completed" in text


def test_the_hook_answers_cursor_with_an_empty_object(capsys, monkeypatch):
    """permission=allow would approve the command. The response stays empty."""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO('{"command": ""}'))
    monkeypatch.setattr("sys.argv", ["cursor_hook.py", "shell"])
    assert main() == 0
    response = json.loads(capsys.readouterr().out)
    assert response == {}
    assert "permission" not in response
