"""The hook logic that used to live in bash, now that it has to run on Windows.

The point of the port is that a hook must not depend on a shell. On native
Windows `bash` resolves to the WSL shim, so a .sh hook runs in a different
operating system from the agent that fired it -- these tests pin the behaviour
that replaced it, including what happens with no tmux anywhere.
"""
import json
import os
import sys

import bridge
import notify
import pytest

ENV_TEXT = (
    "# a comment\n"
    "\n"
    "DISCORD_BOT_TOKEN=aaa.bbb.ccc\n"
    'DISCORD_USER_ID="222222222222222222"\n'
    "AGENT_BRIDGE_STATE=~/.agent-bridge/state.json\n"
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("DISCORD_BOT_TOKEN", "DISCORD_USER_ID", "AGENT_BRIDGE_STATE",
                 "TMUX_SESSION_NAME", "AB_SESSION", "AB_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ reading .env

def test_env_is_read_without_a_shell(tmp_path, clean_env):
    (tmp_path / ".env").write_text(ENV_TEXT)
    bridge.load_env(tmp_path)
    assert os.environ["DISCORD_BOT_TOKEN"] == "aaa.bbb.ccc"


def test_quotes_are_stripped(tmp_path, clean_env):
    (tmp_path / ".env").write_text(ENV_TEXT)
    bridge.load_env(tmp_path)
    assert os.environ["DISCORD_USER_ID"] == "222222222222222222"


def test_a_env_saved_on_windows_does_not_smuggle_a_carriage_return(tmp_path, clean_env):
    """CRLF in .env put a \\r inside the token and Discord answered 401, which
    reads exactly like a wrong token. The shell version needed a separate
    normalisation pass; this one cannot reintroduce it."""
    (tmp_path / ".env").write_text(ENV_TEXT.replace("\n", "\r\n"))
    bridge.load_env(tmp_path)
    assert os.environ["DISCORD_BOT_TOKEN"] == "aaa.bbb.ccc"


def test_a_real_environment_variable_wins_over_the_file(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "from-the-environment")
    (tmp_path / ".env").write_text(ENV_TEXT)
    bridge.load_env(tmp_path)
    assert os.environ["DISCORD_BOT_TOKEN"] == "from-the-environment"


def test_a_missing_env_file_is_not_an_error(tmp_path, clean_env):
    bridge.load_env(tmp_path)          # must not raise


# --------------------------------------------------------------- session names

@pytest.mark.parametrize("folder,expected", [
    ("promptwall", "promptwall"),
    ("CodePulse", "CodePulse"),
    ("my_api-v2", "my_api-v2"),
    ("my.api", "my-api"),
    ("my project (old)", "myprojectold"),
])
def test_a_folder_becomes_the_same_name_the_shell_would_have_made(folder, expected):
    """scripts/lib/session_name.sh has to agree with this exactly, or one
    project ends up with two session names and replies go to the wrong agent."""
    assert bridge.sanitise_session_name(folder) == expected


def test_the_name_comes_from_the_payload_when_there_is_no_tmux(clean_env, monkeypatch):
    """The Windows case: no tmux to ask, so the project directory decides."""
    monkeypatch.setattr(bridge.shutil, "which", lambda _: None)
    assert bridge.session_name({"cwd": "/home/me/code/portfolio"}) == "portfolio"


def test_an_explicit_name_beats_everything(clean_env, monkeypatch):
    monkeypatch.setenv("TMUX_SESSION_NAME", "api-v2")
    assert bridge.session_name({"cwd": "/home/me/somewhere-else"}) == "api-v2"


def test_there_is_always_some_name(clean_env, monkeypatch):
    monkeypatch.setattr(bridge.shutil, "which", lambda _: None)
    assert bridge.session_name({"cwd": "/"}) == "unknown"


def test_no_options_are_invented_where_there_is_no_pane(clean_env, monkeypatch):
    """On Windows there is no tmux and therefore nothing to read. Omitting the
    options is honest; guessing them would not be."""
    monkeypatch.setattr(bridge.shutil, "which", lambda _: None)
    assert bridge.pane_options("anything") == []


# ------------------------------------------------------------- the state file

def test_the_last_session_is_recorded(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("AGENT_BRIDGE_STATE", str(tmp_path / "state.json"))
    bridge.record_last_session("portfolio")
    assert json.loads((tmp_path / "state.json").read_text())["last_session"] == "portfolio"


def test_other_state_survives_being_updated(tmp_path, clean_env, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_session": "old", "something_else": 1}))
    monkeypatch.setenv("AGENT_BRIDGE_STATE", str(path))
    bridge.record_last_session("new")
    state = json.loads(path.read_text())
    assert state["last_session"] == "new" and state["something_else"] == 1


def test_a_corrupt_state_file_is_replaced_rather_than_fatal(tmp_path, clean_env, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    monkeypatch.setenv("AGENT_BRIDGE_STATE", str(path))
    bridge.record_last_session("portfolio")
    assert json.loads(path.read_text())["last_session"] == "portfolio"


# ------------------------------------------------------------- the DM itself

def test_the_finished_message_is_unchanged(clean_env, monkeypatch):
    monkeypatch.setattr(bridge, "pane_options", lambda _: [])
    assert notify.build_message("done", "portfolio", {}) == "✅ [portfolio] Task finished."


def test_the_needs_input_message_is_unchanged(clean_env, monkeypatch):
    monkeypatch.setattr(bridge, "pane_options", lambda _: [])
    out = notify.build_message("input", "portfolio", {"message": "needs permission"})
    assert out == "\U0001f7e1 [portfolio] Needs input: needs permission"


def test_a_payload_with_nothing_useful_still_says_something(clean_env, monkeypatch):
    monkeypatch.setattr(bridge, "pane_options", lambda _: [])
    out = notify.build_message("input", "portfolio", {})
    assert "Agent needs your input" in out


def test_options_are_appended_when_a_prompt_is_on_screen(clean_env, monkeypatch):
    monkeypatch.setattr(bridge, "pane_options",
                        lambda _: ["❯ 1. Yes", "2. No, keep planning"])
    out = notify.build_message("input", "portfolio", {"message": "approve?"})
    assert "1. Yes" in out and "2. No, keep planning" in out
    assert "pick <n>" in out


def test_a_missing_token_is_reported_rather_than_sent_into_the_void(tmp_path, clean_env,
                                                                   monkeypatch, capsys):
    monkeypatch.setattr(notify, "HOOKS_DIR", tmp_path / "hooks")
    monkeypatch.setattr(sys, "argv", ["notify.py", "done"])
    assert notify.main() == 1
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err
