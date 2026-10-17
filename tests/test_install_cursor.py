"""install_cursor merges into hooks.json without dropping hooks you added."""
from install_cursor import hook_command, merge_hooks, remove_hooks


def test_our_hooks_are_added_beside_an_existing_one():
    existing = {"version": 1, "hooks": {"stop": [{"command": "echo hi"}]}}
    merged = merge_hooks(existing, r"C:\Python\python.exe", r"D:\repo")
    commands = [entry["command"] for entry in merged["hooks"]["stop"]]
    assert "echo hi" in commands
    assert any("cursor_hook.py" in command and command.endswith(" stop")
               for command in commands)
    shell = merged["hooks"]["beforeShellExecution"][0]["command"]
    assert shell.endswith(" shell")
    assert "cursor_hook.py" in shell


def test_a_path_with_spaces_is_quoted():
    command = hook_command(r"C:\Program Files\Python\python.exe", r"D:\My Repo", "stop")
    assert command.startswith(r'"C:\Program Files\Python\python.exe"')
    assert r'"D:\My Repo\hooks\cursor_hook.py"' in command


def test_rerunning_replaces_our_entry_instead_of_stacking_it():
    once = merge_hooks({}, "python", "/repo")
    twice = merge_hooks(once, "python3", "/moved")
    stops = twice["hooks"]["stop"]
    assert len(stops) == 1
    assert "python3" in stops[0]["command"]
    assert "moved" in stops[0]["command"]


def test_uninstall_removes_only_ours():
    merged = merge_hooks({"hooks": {"stop": [{"command": "echo hi"}]}}, "python", "/repo")
    left = remove_hooks(merged)
    assert left["hooks"]["stop"] == [{"command": "echo hi"}]
    assert "beforeShellExecution" not in left["hooks"]
