#!/usr/bin/env python3
"""Walk through creating the Discord bot, then prove it actually works.

The developer-portal steps are where people give up, and when they get one
wrong the bridge fails much later with a bare 401 or 403 that says nothing
about which step was missed. So this asks for the two values and immediately
uses them: it looks the bot up, opens the DM channel, and sends a real
message. By the time it prints "done", a message has arrived on your phone.

  scripts/setup_discord.py            fill in .env, checking as it goes
  scripts/setup_discord.py --check    test the credentials already in .env
"""
import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"
EXAMPLE_FILE = REPO / ".env.example"

_COLOUR = sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")
BOLD = "\033[1m" if _COLOUR else ""
DIM = "\033[2m" if _COLOUR else ""
RED = "\033[31m" if _COLOUR else ""
GREEN = "\033[32m" if _COLOUR else ""
YELLOW = "\033[33m" if _COLOUR else ""
OFF = "\033[0m" if _COLOUR else ""

STEPS = f"""
{BOLD}Creating the Discord bot{OFF}

  1. Open https://discord.com/developers/applications and click
     {BOLD}New Application{OFF}. Any name will do.

  2. {BOLD}Bot{OFF} tab -> {BOLD}Reset Token{OFF} -> copy it. Leave all three
     Privileged Gateway Intents OFF; this bot does not need them.
     {DIM}Treat that token like a password: it is full control of the bot.{OFF}

  3. {BOLD}Installation{OFF} tab -> under Guild Install set scope {BOLD}bot{OFF}
     and tick the {BOLD}Send Messages{OFF} permission. Copy the Install Link.

  4. A bot can only DM you if you share a server with it. Make a throwaway
     private server ({BOLD}+{OFF} in the sidebar -> Create My Own), then open
     the install link and add the bot to it. You never have to use that
     server again.

  5. In that server: {BOLD}right-click it -> Privacy Settings -> Direct
     Messages ON{OFF}. {YELLOW}This is the most common trap{OFF} -- with it off
     the DM is rejected even though everything else is correct.

  6. Your own user ID: {BOLD}User Settings -> Advanced -> Developer Mode{OFF}
     ON, then right-click {BOLD}your own name{OFF} -> Copy User ID.
"""


def request(method, path, token, payload=None):
    """Return (status, body). Never raises on an HTTP error status."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": "Bot " + token,
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (agent-bridge, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw.strip() or "(no body)"}
    except urllib.error.URLError as e:
        return 0, {"message": f"could not reach discord.com: {e.reason}"}


def check_token(token):
    """(ok, message, bot). Names the likely mistake wherever it can."""
    if token.count(".") != 2:
        return False, (
            "That does not look like a bot token -- a bot token has two dots in "
            "it.\n     You may have copied the Application ID or the Public Key "
            "from the\n     General Information tab. The token is on the Bot "
            "tab, behind the\n     Reset Token button."
        ), None

    status, body = request("GET", "/users/@me", token)
    if status == 200:
        return True, "authenticated as " + str(body.get("username")), body
    if status == 401:
        return False, (
            "Discord rejected that token (401).\n"
            "     Either it was copied incompletely, or it was reset in the "
            "portal after\n     you copied it -- pressing Reset Token "
            "invalidates the previous one."
        ), None
    if status == 0:
        return False, body.get("message", "network error"), None
    return False, f"unexpected reply from Discord ({status}): {body.get('message')}", None


def check_dm(token, user_id, bot=None):
    """Open the DM channel and actually send a message through it."""
    if not re.fullmatch(r"\d{15,25}", user_id):
        return False, (
            "That is not a Discord user ID -- an ID is 17-19 digits and nothing "
            "else.\n     If you copied a username, turn on User Settings -> "
            "Advanced ->\n     Developer Mode first, then right-click your name "
            "-> Copy User ID."
        )
    if bot and str(bot.get("id")) == user_id:
        return False, (
            "That is the bot's own user ID, not yours. Right-click your own "
            "name in\n     the member list rather than the bot's."
        )

    status, body = request("POST", "/users/@me/channels", token,
                           {"recipient_id": user_id})
    if status != 200:
        if body.get("code") in (10013, 50033) or status == 404:
            return False, (
                "Discord has no user with that ID.\n"
                "     Check you copied your own ID and not a server or channel "
                "ID -- all\n     three look like long numbers."
            )
        return False, f"could not open a DM channel ({status}): {body.get('message')}"

    channel_id = body["id"]
    status, body = request(
        "POST", f"/channels/{channel_id}/messages", token,
        {"content": "agent-bridge is connected. "
                    "Replies you send here reach your agents."},
    )
    if status == 200:
        return True, "test message sent -- check your Discord DMs"
    if body.get("code") == 50007:
        return False, (
            "The bot is not allowed to DM you (50007). Two causes, in the order "
            "they\n     are usually the problem:\n"
            "       a) you do not share a server with the bot yet -- step 4\n"
            "       b) that server's Privacy Settings -> Direct Messages is off "
            "-- step 5"
        )
    return False, f"could not send the DM ({status}): {body.get('message')}"


def render_env(base, token, user_id):
    """The new .env text: the two credentials replaced, everything else kept."""
    lines, seen = [], set()
    for line in base.splitlines():
        key = line.split("=", 1)[0].strip()
        if key == "DISCORD_BOT_TOKEN":
            lines.append("DISCORD_BOT_TOKEN=" + token)
        elif key == "DISCORD_USER_ID":
            lines.append("DISCORD_USER_ID=" + user_id)
        else:
            lines.append(line)
            continue
        seen.add(key)
    for key, value in (("DISCORD_BOT_TOKEN", token), ("DISCORD_USER_ID", user_id)):
        if key not in seen:
            lines.append(key + "=" + value)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_env(token, user_id):
    base = ""
    if ENV_FILE.exists():
        base = ENV_FILE.read_text(encoding="utf-8")
    elif EXAMPLE_FILE.exists():
        base = EXAMPLE_FILE.read_text(encoding="utf-8")

    # newline="" keeps the explicit "\n" from becoming CRLF on Windows: a .env
    # with carriage returns smuggles one into the token, and Discord answers 401.
    with open(ENV_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(render_env(base, token, user_id))
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass          # a Windows drive mounted under WSL cannot; not fatal


def read_env():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def ok(message):
    print(f"  {GREEN}ok{OFF}    {message}")


def bad(message):
    print(f"  {RED}FAIL{OFF}  {message}")


def do_check():
    values = read_env()
    token = values.get("DISCORD_BOT_TOKEN", "")
    user_id = values.get("DISCORD_USER_ID", "")
    if not token or "your-bot-token" in token:
        bad(f"{ENV_FILE} has no bot token yet -- run this without --check.")
        return 1

    print(f"\n{BOLD}==> Checking the credentials in .env{OFF}")
    good, message, bot = check_token(token)
    (ok if good else bad)(message)
    if not good:
        return 1
    good, message = check_dm(token, user_id, bot)
    (ok if good else bad)(message)
    return 0 if good else 1


def ask_until_valid(prompt, validate, hidden=False, tries=3):
    """Ask up to `tries` times. Returns the accepted value, or None."""
    for attempt in range(tries):
        answer = (getpass.getpass(prompt) if hidden else input(prompt)).strip()
        if not answer:
            continue
        good, message, *rest = validate(answer)
        (ok if good else bad)(message)
        if good:
            return (answer, *rest) if rest else (answer,)
        if attempt == tries - 1:
            print("\n  Nothing was written. Fix the step above and re-run.")
    return None


def do_setup():
    if not sys.stdin.isatty():
        print("setup_discord: needs a terminal to ask questions "
              "(use --check to test an existing .env)", file=sys.stderr)
        return 2

    if read_env().get("DISCORD_BOT_TOKEN", "").count(".") == 2:
        print(f"{ENV_FILE} already has a token.")
        if input("Replace it? [y/N] ").strip().lower() not in ("y", "yes"):
            return do_check()

    print(STEPS)
    input(f"  {DIM}Press Enter once you have finished step 6.{OFF} ")

    got = ask_until_valid("\n  Paste the bot token (it stays hidden): ",
                          check_token, hidden=True)
    if not got:
        return 1
    token, bot = got

    got = ask_until_valid(
        "\n  Paste your own Discord user ID: ",
        lambda value: check_dm(token, value, bot),
    )
    if not got:
        return 1
    user_id = got[0]

    write_env(token, user_id)
    print(f"\n  {GREEN}Done.{OFF} Credentials written to {ENV_FILE}")
    print(f"  {DIM}A test message is already waiting in your Discord DMs.{OFF}")
    print("\n  Next:  scripts/bot_ctl.sh restart")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Set up the Discord bot and verify it can reach you.")
    parser.add_argument("--check", action="store_true",
                        help="test the credentials already in .env and exit")
    args = parser.parse_args()
    return do_check() if args.check else do_setup()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ncancelled -- nothing was written")
        sys.exit(130)
