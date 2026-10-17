"""How each coding agent is launched, and how we notice it is waiting.

Claude Code is the only one with a Notification hook that means "blocked on
you". The others are either a Cursor hook that fires when a shell command is
proposed, or a tmux pane we have to watch. The reply path is unchanged: text
is typed into the pane. Nothing here can press a button in the Cursor IDE.
"""

# The poller's historical default. Agents without a measured prompt share it
# and are expected to be tuned; inventing a per-tool UI string would notify
# on the wrong line.
GENERIC_PROMPT = r"\?\s*$|\(y/n\)|approve|Continue\?|Allow\?"

# Cursor's CLI docs say it asks you to approve (y) or reject (n). The IDE
# does not show that prompt; it has its own Run button, which a hook can
# report but not click.
CURSOR_PROMPT = r"\(y/n\)|approve \(y\)|reject \(n\)"


class Agent:
    def __init__(self, agent_id, command, hooks, prompt_regex):
        self.id = agent_id
        self.command = command
        self.hooks = hooks          # "claude", "cursor", or None
        self.prompt_regex = prompt_regex


AGENTS = {
    "claude": Agent("claude", "claude", "claude", None),
    "cursor": Agent("cursor", "agent", "cursor", CURSOR_PROMPT),
    "codex": Agent("codex", "codex", None, GENERIC_PROMPT),
    "gemini": Agent("gemini", "gemini", None, GENERIC_PROMPT),
}


def resolve(command):
    """Turn a start_session argument into the command tmux should run.

    A known name selects that agent. Extra words are arguments to its real
    binary, so `cursor --mode ask` launches `agent --mode ask` and not a
    program called cursor. Anything else is run as given, with no poller:
    watching an arbitrary shell would notify on ordinary prompts.
    """
    raw = (command or "").strip() or "claude"
    head, _, rest = raw.partition(" ")
    agent = AGENTS.get(head)
    if agent is None:
        return {"id": None, "command": raw, "prompt_regex": None, "hooks": None}
    launched = agent.command if not rest else f"{agent.command} {rest}"
    return {
        "id": agent.id,
        "command": launched,
        "prompt_regex": agent.prompt_regex,
        "hooks": agent.hooks,
    }
