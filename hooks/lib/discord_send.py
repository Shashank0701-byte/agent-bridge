"""Send a DM as the bridge bot.

Shared by notify.sh and ask_options.sh. Webhooks cannot post to a DM, so this
goes through the bot REST API: open the DM channel (idempotent -- Discord
returns the existing one), then post to it.

Usage:  python3 discord_send.py "message text"
        python3 discord_send.py --stdin
Requires DISCORD_BOT_TOKEN and DISCORD_USER_ID in the environment.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
LIMIT = 2000  # Discord's hard cap on message content


def _post(url, payload, token):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (agent-bridge, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def chunk(text, limit=LIMIT):
    """Split on line boundaries so a long question card stays readable."""
    out, cur = [], ""
    for line in text.split("\n"):
        if len(line) > limit:                      # pathological single line
            if cur:
                out.append(cur)
                cur = ""
            for i in range(0, len(line), limit):
                out.append(line[i:i + limit])
            continue
        if len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out or [""]


def send_dm(text):
    token = os.environ["DISCORD_BOT_TOKEN"]
    user_id = str(os.environ["DISCORD_USER_ID"])
    channel = _post(f"{API}/users/@me/channels", {"recipient_id": user_id}, token)
    for part in chunk(text):
        _post(f"{API}/channels/{channel['id']}/messages", {"content": part}, token)


def main():
    text = sys.stdin.read() if sys.argv[1:2] == ["--stdin"] else sys.argv[1]
    try:
        send_dm(text)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"discord_send: API returned {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"discord_send: could not send DM: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
