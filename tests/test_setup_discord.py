"""The guided Discord setup.

Its reason to exist is the error messages: a wrong value in the developer
portal used to surface much later as a bare 401 or 403 that named no step. So
what is actually worth testing is that each failure mode produces the message
that tells you which step to go back to. No network is involved -- `request`
is replaced with a scripted set of replies.
"""
import pytest
import setup_discord as sd

BOT = {"id": "111111111111111111", "username": "bridge-bot"}
ME = "222222222222222222"


@pytest.fixture
def replies(monkeypatch):
    """Queue up (status, body) pairs; records the calls that were made."""
    queued, calls = [], []

    def fake_request(method, path, token, payload=None):
        calls.append((method, path, payload))
        return queued.pop(0)

    monkeypatch.setattr(sd, "request", fake_request)
    return queued, calls


# ------------------------------------------------------------------- the token

def test_a_token_with_no_dots_is_caught_before_any_request(replies):
    queued, calls = replies
    good, message, bot = sd.check_token("1234567890abcdef")
    assert not good and not calls          # never bothered Discord
    assert "two dots" in message and "Reset Token" in message


def test_a_rejected_token_explains_that_resetting_invalidates_the_old_one(replies):
    queued, _ = replies
    queued.append((401, {"message": "401: Unauthorized"}))
    good, message, _ = sd.check_token("aaa.bbb.ccc")
    assert not good
    assert "401" in message and "Reset Token" in message


def test_a_good_token_reports_the_bot_it_belongs_to(replies):
    queued, calls = replies
    queued.append((200, BOT))
    good, message, bot = sd.check_token("aaa.bbb.ccc")
    assert good and bot == BOT
    assert "bridge-bot" in message
    assert calls == [("GET", "/users/@me", None)]


def test_an_unreachable_discord_says_so_rather_than_blaming_the_token(replies):
    queued, _ = replies
    queued.append((0, {"message": "could not reach discord.com: timed out"}))
    good, message, _ = sd.check_token("aaa.bbb.ccc")
    assert not good and "could not reach" in message


# ----------------------------------------------------------------- the user ID

@pytest.mark.parametrize("value", ["shashank", "@me", "", "12345", "not-an-id"])
def test_something_that_is_not_an_id_is_caught_before_any_request(replies, value):
    queued, calls = replies
    good, message = sd.check_dm("aaa.bbb.ccc", value)
    assert not good and not calls
    assert "Developer Mode" in message


def test_copying_the_bots_own_id_is_named_as_the_mistake(replies):
    queued, calls = replies
    good, message = sd.check_dm("aaa.bbb.ccc", BOT["id"], BOT)
    assert not good and not calls
    assert "bot's own user ID" in message


def test_an_id_no_user_has_is_distinguished_from_a_blocked_dm(replies):
    queued, _ = replies
    queued.append((400, {"code": 50033, "message": "Invalid Form Body"}))
    good, message = sd.check_dm("aaa.bbb.ccc", ME, BOT)
    assert not good
    assert "no user with that ID" in message


def test_a_blocked_dm_points_at_both_of_its_causes(replies):
    """50007 is the trap the README warns about, and it has two distinct
    causes. Naming only one of them sends half the people down the wrong path."""
    queued, _ = replies
    queued.append((200, {"id": "999"}))
    queued.append((403, {"code": 50007,
                         "message": "Cannot send messages to this user"}))
    good, message = sd.check_dm("aaa.bbb.ccc", ME, BOT)
    assert not good
    assert "step 4" in message and "step 5" in message


def test_success_means_a_message_was_really_sent(replies):
    """Not just that the DM channel opened -- opening it succeeds even when
    sending is refused, which is exactly how 50007 slips through."""
    queued, calls = replies
    queued.append((200, {"id": "999"}))
    queued.append((200, {"id": "msg-1"}))
    good, message = sd.check_dm("aaa.bbb.ccc", ME, BOT)
    assert good and "check your Discord DMs" in message
    assert calls[0] == ("POST", "/users/@me/channels", {"recipient_id": ME})
    assert calls[1][0:2] == ("POST", "/channels/999/messages")
    assert calls[1][2]["content"]


# --------------------------------------------------------------- writing .env

EXAMPLE = (
    "# Discord application credentials.\n"
    "DISCORD_BOT_TOKEN=your-bot-token-from-the-discord-developer-portal\n"
    "\n"
    "# Your own numeric Discord user ID\n"
    "DISCORD_USER_ID=your_numeric_discord_user_id\n"
    "\n"
    "AGENT_BRIDGE_STATE=~/.agent-bridge/state.json\n"
)


def test_both_credentials_are_filled_in():
    out = sd.render_env(EXAMPLE, "aaa.bbb.ccc", ME)
    assert "DISCORD_BOT_TOKEN=aaa.bbb.ccc" in out
    assert f"DISCORD_USER_ID={ME}" in out


def test_other_settings_and_comments_are_kept():
    out = sd.render_env(EXAMPLE, "aaa.bbb.ccc", ME)
    assert "AGENT_BRIDGE_STATE=~/.agent-bridge/state.json" in out
    assert "# Discord application credentials." in out


def test_missing_keys_are_appended_rather_than_lost():
    out = sd.render_env("AGENT_BRIDGE_STATE=~/x\n", "aaa.bbb.ccc", ME)
    assert "DISCORD_BOT_TOKEN=aaa.bbb.ccc" in out
    assert f"DISCORD_USER_ID={ME}" in out
    assert "AGENT_BRIDGE_STATE=~/x" in out


def test_rerunning_replaces_rather_than_duplicates():
    once = sd.render_env(EXAMPLE, "aaa.bbb.ccc", ME)
    twice = sd.render_env(once, "ddd.eee.fff", "333333333333333333")
    assert twice.count("DISCORD_BOT_TOKEN=") == 1
    assert twice.count("DISCORD_USER_ID=") == 1
    assert "aaa.bbb.ccc" not in twice


def test_the_result_never_contains_a_carriage_return():
    """A .env with CRLF smuggles a \\r into the token, and Discord answers 401
    -- which reads exactly like a wrong token and wastes an afternoon."""
    out = sd.render_env(EXAMPLE.replace("\n", "\r\n"), "aaa.bbb.ccc", ME)
    assert "\r" not in out


def test_the_file_ends_with_exactly_one_newline():
    out = sd.render_env(EXAMPLE, "aaa.bbb.ccc", ME)
    assert out.endswith("\n") and not out.endswith("\n\n")
