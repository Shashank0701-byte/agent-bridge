"""agent-bridge setup | bot | session

Finds the installed scripts and runs them. The shell scripts stay the source
of truth for tmux, the supervisor lock, and the Claude hook merge.
"""
import os
import shutil
import subprocess
import sys

from agent_bridge.paths import project_root

USAGE = """\
usage: agent-bridge setup [--no-wrapper] [--cursor]
       agent-bridge bot start|stop|status|logs|restart
       agent-bridge session [project-dir] [agent]

setup     install hooks, the Discord bot, and (by default) the claude wrapper
bot       start or stop the process that types replies into tmux
session   open a tmux session for claude, cursor, codex, or gemini

--cursor  also wire Cursor's beforeShellExecution and stop hooks
"""


def _bash():
    return shutil.which("bash")


def _run(argv, env=None):
    return subprocess.run(argv, env=env).returncode


def setup(root, args):
    cursor = "--cursor" in args
    forwarded = [arg for arg in args if arg != "--cursor"]
    env = os.environ.copy()
    env["AGENT_BRIDGE_PYTHON"] = sys.executable
    env["AGENT_BRIDGE_ROOT"] = str(root)

    code = 0
    bash = _bash()
    # `setup --cursor` on its own is the Windows notification path and does
    # not need bash. Anything else is the tmux install.
    if forwarded or not cursor:
        if not bash:
            print("agent-bridge: bash is required for setup "
                  "(tmux, the Claude hooks, and the bot).", file=sys.stderr)
            print("On native Windows, use: agent-bridge setup --cursor", file=sys.stderr)
            return 1
        code = _run([bash, str(root / "scripts" / "bootstrap.sh"), *forwarded], env)

    if cursor:
        script = root / "scripts" / "install_cursor.py"
        code = code or _run([sys.executable, str(script)], env)
    return code


def bot(root, args):
    bash = _bash()
    if not bash:
        print("agent-bridge: bash is required to supervise the bot.", file=sys.stderr)
        return 1
    if not args:
        args = ["status"]
    os.execv(bash, [bash, str(root / "scripts" / "bot_ctl.sh"), *args])


def session(root, args):
    bash = _bash()
    if not bash:
        print("agent-bridge: bash and tmux are required to open a session.", file=sys.stderr)
        return 1
    os.execv(bash, [bash, str(root / "scripts" / "start_session.sh"), *args])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0 if argv else 2

    root = project_root()
    command, args = argv[0], argv[1:]
    if command == "setup":
        return setup(root, args)
    if command == "bot":
        return bot(root, args)
    if command == "session":
        return session(root, args)
    print(f"agent-bridge: unknown command {command!r}\n", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
