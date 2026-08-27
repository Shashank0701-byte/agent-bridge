<#
    Wire the outbound hooks into native Windows Claude Code -- no WSL involved.

    This gets you the DM half of the bridge in PowerShell: permission prompts,
    question cards and task-finished all reach your phone from a `claude`
    session running natively. Replying from Discord still needs the WSL setup,
    because typing back into a live session needs tmux and Windows has no
    equivalent. See the README section "Windows without WSL".

        .\scripts\install_windows.ps1
        .\scripts\install_windows.ps1 -Uninstall

    The hook commands point at python and the .py files directly, never at the
    .sh wrappers: `bash` on a normal Windows PATH is the WSL shim, so a .sh hook
    would run inside a different operating system from the agent that fired it,
    with a different view of the filesystem.
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$settingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'

function Say($msg)  { Write-Host "    $msg" }
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Bad($msg)  { Write-Host "    $msg" -ForegroundColor Red }

# ------------------------------------------------------------------ python ---
Step 'Python'
if (-not $Python) {
    foreach ($candidate in 'python', 'python3', 'py') {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source; break }
    }
}
if (-not $Python) {
    Bad 'No python on PATH. Install Python 3, or pass -Python C:\path\to\python.exe'
    exit 1
}
Say "using $Python"

# The hooks are standard library only, deliberately, so this should never fail
# on a working interpreter -- and if it does, better to know now than to find
# out from a notification that never arrives.
& $Python -c "import json,urllib.request,pathlib" 2>$null
if ($LASTEXITCODE -ne 0) { Bad "$Python cannot import the standard library"; exit 1 }
Say 'standard library present'

# -------------------------------------------------------------------- .env ---
Step 'Credentials'
$envFile = Join-Path $repo '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repo '.env.example') $envFile
    Say 'created .env from the example'
}
if ((Get-Content $envFile -Raw) -match 'your-bot-token|your_numeric') {
    Say 'still on placeholders -- run this to fill it in and check it works:'
    Say "  $Python `"$repo\scripts\setup_discord.py`""
} else {
    Say '.env has credentials in it'
}

# ------------------------------------------------------------------- hooks ---
Step $(if ($Uninstall) { 'Removing hooks' } else { 'Wiring hooks into Claude Code' })

$merge = @'
import json, os, sys

settings_path, repo, python, mode = sys.argv[1:5]

def cmd(script, *args):
    parts = [python, os.path.join(repo, "hooks", script), *args]
    return " ".join(f'"{p}"' if " " in p else p for p in parts)

new = {
    "PreToolUse": [{"matcher": "AskUserQuestion",
                    "hooks": [{"type": "command", "command": cmd("ask_options.py")}]}],
    "Notification": [{"matcher": "permission_prompt|agent_needs_input|elicitation_dialog|elicitation_url_dialog",
                      "hooks": [{"type": "command", "command": cmd("notify.py", "input")}]}],
    "Stop": [{"hooks": [{"type": "command", "command": cmd("notify.py", "done")}]}],
}

current = {}
if os.path.exists(settings_path):
    try:
        text = open(settings_path, encoding="utf-8").read().strip()
        current = json.loads(text) if text else {}
    except json.JSONDecodeError as e:
        sys.exit(f"{settings_path} is not valid JSON ({e}); fix it and re-run")

OURS = ("notify.py", "ask_options.py", "notify.sh", "ask_options.sh")

def ours(entry):
    return any(any(name in (h.get("command") or "") for name in OURS)
               for h in entry.get("hooks", []))

hooks = current.get("hooks") or {}
for event in set(list(hooks) + list(new)):
    kept = [e for e in (hooks.get(event) or []) if not ours(e)]
    if mode == "install" and event in new:
        hooks[event] = kept + new[event]
        print(f"  {event}: kept {len(kept)} existing hook(s), added ours"
              if kept else f"  {event}: added")
    else:
        removed = len(hooks.get(event) or []) - len(kept)
        if removed:
            print(f"  {event}: removed {removed} of ours")
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)

if hooks:
    current["hooks"] = hooks
else:
    current.pop("hooks", None)

tmp = settings_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(current, f, indent=2)
    f.write("\n")
os.replace(tmp, settings_path)
print(f"  wrote {settings_path}")
'@

New-Item -ItemType Directory -Force (Split-Path $settingsPath) | Out-Null
if (Test-Path $settingsPath) {
    $backup = "$settingsPath.bak-$(Get-Date -Format yyyyMMddHHmmss)"
    Copy-Item $settingsPath $backup
    Say "backed up to $backup"
}

$mergeFile = Join-Path ([System.IO.Path]::GetTempPath()) "agent-bridge-merge.py"
Set-Content -Path $mergeFile -Value $merge -Encoding UTF8
try {
    & $Python $mergeFile $settingsPath $repo $Python $(if ($Uninstall) { 'uninstall' } else { 'install' })
    if ($LASTEXITCODE -ne 0) { Bad 'could not update settings.json'; exit 1 }
} finally {
    Remove-Item $mergeFile -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------ report ---
if ($Uninstall) {
    Write-Host "`nHooks removed. Native Claude Code will stop sending DMs." -ForegroundColor Green
    exit 0
}

Write-Host "`n==================== what you have now ====================" -ForegroundColor Cyan
Write-Host '  Outbound  DMs from a native `claude` session in PowerShell'
Write-Host '  Inbound   replying from Discord still needs the WSL setup (install.ps1)'
Write-Host ''
Write-Host 'Check it end to end:' -ForegroundColor Cyan
Write-Host "  $Python `"$repo\scripts\setup_discord.py`" --check"
Write-Host ''
Write-Host 'Then open a new PowerShell, cd to any project, and run claude.'
