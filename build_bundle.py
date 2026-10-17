"""Copy the scripts a pip install has to run into the built package.

setup() calls the shell scripts that already exist. They are not a Python
package, so a wheel would otherwise contain only agent_bridge/*.py and the
command would have nothing to hand over to.
"""
import shutil
from pathlib import Path

from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
TREES = ("scripts", "hooks", "bot", "config", "poller")
FILES = ("requirements.txt", ".env.example")


class BuildPy(build_py):
    def run(self):
        super().run()
        dest = Path(self.build_lib) / "agent_bridge" / "_bundle"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for name in TREES:
            shutil.copytree(
                ROOT / name,
                dest / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for name in FILES:
            shutil.copy2(ROOT / name, dest / name)
