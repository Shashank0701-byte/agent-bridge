"""Make the bridge's modules importable without installing them as a package.

bot.py, ask_options.py and discord_send.py are run as scripts in production,
so there is no package to import. Adding their directories to sys.path keeps
the tests honest -- they exercise the same files that actually run.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in (ROOT / "bot", ROOT / "hooks", ROOT / "hooks" / "lib"):
    sys.path.insert(0, str(d))
