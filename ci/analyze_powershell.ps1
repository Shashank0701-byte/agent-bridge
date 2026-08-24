<#
    Static checks for the Windows installer.

    install.ps1 is the one part of this project CI can never run -- GitLab's
    free tier has no Windows runners, and the script drives wsl.exe. So the
    goal here is narrow but worth having: catch a file that does not even parse
    before a friend runs it on their machine and gets a wall of red.

    Parse errors and analyzer Errors fail the job. Warnings are printed and do
    not, because they are style opinions. A PSGallery outage warns rather than
    failing: it must not be able to block a merge.
#>
$ErrorActionPreference = 'Stop'
$failed = $false

$files = Get-ChildItem -Path . -Filter *.ps1 -Recurse |
         Where-Object { $_.FullName -notmatch '[\/]\.git[\/]' }

if (-not $files) { Write-Host 'no .ps1 files found'; exit 0 }

Write-Host "`n==> Parsing $($files.Count) PowerShell file(s)"
foreach ($f in $files) {
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $f.FullName, [ref]$null, [ref]$errors) | Out-Null
    $rel = Resolve-Path -Relative $f.FullName
    if ($errors -and $errors.Count -gt 0) {
        $failed = $true
        Write-Host "  FAIL  $rel"
        foreach ($e in $errors) {
            Write-Host "        line $($e.Extent.StartLineNumber): $($e.Message)"
        }
    } else {
        Write-Host "  ok    $rel"
    }
}

Write-Host "`n==> PSScriptAnalyzer"
if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
    try {
        Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction Stop
        Install-Module PSScriptAnalyzer -Force -Scope CurrentUser -ErrorAction Stop
    } catch {
        Write-Host "  skipped: could not install PSScriptAnalyzer ($($_.Exception.Message))"
        if ($failed) { exit 1 } else { exit 0 }
    }
}
Import-Module PSScriptAnalyzer

$results = Invoke-ScriptAnalyzer -Path . -Recurse -ExcludeRule PSAvoidUsingWriteHost
$errors   = @($results | Where-Object Severity -eq 'Error')
$warnings = @($results | Where-Object Severity -ne 'Error')

foreach ($w in $warnings) {
    Write-Host "  warn  $($w.ScriptName):$($w.Line) $($w.RuleName): $($w.Message)"
}
foreach ($e in $errors) {
    $failed = $true
    Write-Host "  FAIL  $($e.ScriptName):$($e.Line) $($e.RuleName): $($e.Message)"
}
if ($errors.Count -eq 0) {
    Write-Host "  ok    no errors ($($warnings.Count) warning(s))"
}

Write-Host ''
if ($failed) { Write-Host 'powershell: failed'; exit 1 }
Write-Host 'powershell: passed'
exit 0
