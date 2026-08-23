<#
  agent-bridge one-command setup for Windows.

      .\install.ps1

  Installs WSL2 + Ubuntu if needed, then runs scripts/bootstrap.sh inside the
  distro and registers the bot to start at logon. Idempotent: re-run any time.

  Not admin-only: only the very first `wsl --install` needs elevation, and the
  script tells you when that is the case instead of failing obscurely.
#>
param(
  [string]$Distro     = "Ubuntu-24.04",
  [switch]$NoWrapper,
  [switch]$NoAutostart
)
$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = 1

# wsl.exe writes chatter to stderr on a fresh distro -- e.g. "Failed to start
# the systemd user session for 'root'" -- which is a warning, not a failure.
# With ErrorActionPreference=Stop, PowerShell promotes native stderr to a
# terminating NativeCommandError and the whole install dies on a warning.
$PSNativeCommandUseErrorActionPreference = $false

function Invoke-Wsl {
    <#  Runs wsl.exe, returning stdout and the real exit code, without letting
        stderr abort the script. Callers decide what counts as failure.  #>
    # Takes ONE array. Do not use ValueFromRemainingArguments here: PowerShell
    # treats "--" as its own end-of-parameters token and swallows it along with
    # -d/-u, so `Invoke-Wsl -d X -u root -- bash f` would run `wsl X root bash f`
    # against the DEFAULT distro. An explicit array is never re-parsed.
    param([Parameter(Mandatory = $true)][string[]]$WslArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = & wsl @WslArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    $stdout = ($raw | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } |
               Out-String).Trim()
    $stderr = ($raw | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } |
               Out-String).Trim()
    [pscustomobject]@{ Out = $stdout; Err = $stderr; Code = $code }
}

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Info($m) { Write-Host "    $m" }
function Die($m)  { Write-Host "    $m" -ForegroundColor Red; exit 1 }

$repoWin = $PSScriptRoot
$drive   = $repoWin.Substring(0,1).ToLower()
$repoWsl = "/mnt/$drive" + $repoWin.Substring(2).Replace('\','/')

Step "Checking WSL"
$wslOk = $false
try { wsl --status *>$null; $wslOk = ($LASTEXITCODE -eq 0) } catch { $wslOk = $false }

if (-not $wslOk) {
  Info "WSL is not installed."
  Info "Run this ONCE in an Administrator PowerShell, reboot, then re-run this script:"
  Write-Host "`n    wsl --install`n" -ForegroundColor Yellow
  exit 1
}
Ok "WSL present"

Step "Checking distro '$Distro'"
$installed = (Invoke-Wsl @("-l", "-q")).Out -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($installed -contains $Distro) {
  Info "already installed"
} else {
  Info "installing $Distro (this downloads ~500MB and takes a few minutes)..."
  $inst = Invoke-Wsl @("--install", "-d", $Distro, "--no-launch")
  if ($inst.Code -ne 0) { Die "failed to install ${Distro}: $($inst.Err)" }
  Ok "installed"
}

Step "Checking distro user"
# --no-launch leaves the distro with no user account, so create one and make it
# the default. Passwordless sudo: there is no way to answer a password prompt
# during an unattended setup. Undo with: sudo rm /etc/sudoers.d/90-<user>
# Ask root whether a normal login user exists, rather than inferring it from
# `whoami`: on a fresh distro whoami's output can be buried in startup warnings,
# and the default user is not configured yet anyway.
$probe = Invoke-Wsl @("-d", $Distro, "-u", "root", "--", "bash", "-c", "getent passwd 1000 | cut -d: -f1")
$existing = ($probe.Out -split "`r?`n" | Where-Object { $_ -match '^[a-z_][a-z0-9_-]*$' } |
             Select-Object -First 1)
if (-not $existing) {
  $user = $env:USERNAME.ToLower() -replace '[^a-z0-9_-]',''
  if (-not $user) { $user = "dev" }
  Info "creating user '$user'"
  $setup = @"
set -e
id $user >/dev/null 2>&1 || { useradd -m -s /bin/bash $user; usermod -aG sudo $user; }
echo '$user ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-$user
chmod 440 /etc/sudoers.d/90-$user
# Preserve systemd: Ubuntu's WSL images enable it by default, and overwriting
# wsl.conf without it silently turns systemd off for everything else.
printf '[boot]\nsystemd=true\n\n[user]\ndefault=$user\n\n[interop]\nappendWindowsPath=true\n' > /etc/wsl.conf
"@ -replace "`r`n","`n"
  $tmp = Join-Path $env:TEMP "ab_user.sh"
  [IO.File]::WriteAllText($tmp, $setup)
  $tmpWsl = "/mnt/" + $tmp.Substring(0,1).ToLower() + $tmp.Substring(2).Replace('\','/')
  $mk = Invoke-Wsl @("-d", $Distro, "-u", "root", "--", "bash", $tmpWsl)
  if ($mk.Code -ne 0) { Die "could not create the WSL user: $($mk.Err)" }
  Remove-Item $tmp -Force
  $null = Invoke-Wsl @("--terminate", $Distro)    # restart so the default user takes effect
  Ok "created '$user' and set as default"
} else {
  Info "using existing user '$existing'"
}

Step "Running bootstrap inside $Distro"
Info "repo: $repoWsl"
$bootstrapArgs = @("-d", $Distro, "--", "bash", "$repoWsl/scripts/bootstrap.sh")
if ($NoWrapper) { $bootstrapArgs += "--no-wrapper" }
$boot = Invoke-Wsl $bootstrapArgs
$boot.Out | ForEach-Object { $_ }
if ($boot.Err) { $boot.Err }
$bootstrapCode = $boot.Code

if (-not $NoAutostart) {
  Step "Registering logon autostart"
  & (Join-Path $PSScriptRoot "scripts\install_autostart.ps1") -Distro $Distro | ForEach-Object { Info $_ }
}

Step "Done"
Write-Host @"
    Open Ubuntu with:   wsl -d $Distro
    Then:               cd /mnt/<your project> && claude

    Your Windows drives are under /mnt/c, /mnt/d, ...
    Manage the bot:     $repoWsl/scripts/bot_ctl.sh status|logs|restart
"@
if ($bootstrapCode -ne 0) {
  Write-Host "`n    Bootstrap reported problems - see the summary above." -ForegroundColor Yellow
  exit 1
}
