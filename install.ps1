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
$installed = (wsl -l -q) -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($installed -contains $Distro) {
  Info "already installed"
} else {
  Info "installing $Distro (this downloads ~500MB and takes a few minutes)..."
  wsl --install -d $Distro --no-launch
  if ($LASTEXITCODE -ne 0) { Die "failed to install $Distro" }
  Ok "installed"
}

Step "Checking distro user"
# --no-launch leaves the distro with no user account, so create one and make it
# the default. Passwordless sudo: there is no way to answer a password prompt
# during an unattended setup. Undo with: sudo rm /etc/sudoers.d/90-<user>
$who = (wsl -d $Distro -- whoami 2>$null)
if (-not $who -or $who.Trim() -eq "root") {
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
  wsl -d $Distro -u root -- bash $tmpWsl
  if ($LASTEXITCODE -ne 0) { Die "could not create the WSL user" }
  Remove-Item $tmp -Force
  wsl --terminate $Distro | Out-Null    # restart so the default user takes effect
  Ok "created '$user' and set as default"
} else {
  Info "using existing user '$($who.Trim())'"
}

Step "Running bootstrap inside $Distro"
Info "repo: $repoWsl"
$bootstrapArgs = @("-d", $Distro, "--", "bash", "$repoWsl/scripts/bootstrap.sh")
if ($NoWrapper) { $bootstrapArgs += "--no-wrapper" }
wsl @bootstrapArgs
$bootstrapCode = $LASTEXITCODE

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
