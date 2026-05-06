#!/usr/bin/env bash
# Validate PowerShell script syntax across the repo via AST parse.
# Requires PowerShell 7+ (pwsh) to be on PATH.
#
# Install on Debian/Ubuntu:
#   wget -q https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb
#   sudo dpkg -i packages-microsoft-prod.deb && rm packages-microsoft-prod.deb
#   sudo apt-get update && sudo apt-get install -y powershell
#
# Usage:
#   ./scripts/check-ps-syntax.sh
# Exits non-zero on any parse error.

set -euo pipefail

if ! command -v pwsh >/dev/null 2>&1; then
    echo "pwsh (PowerShell 7+) not found on PATH. See header of this file for install instructions." >&2
    exit 2
fi

cd "$(dirname "$0")/.."

pwsh -NoProfile -Command '
$repo = (Get-Location).Path
$failed = 0
Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object {
    $errors = $null
    $tokens = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
    $rel = $_.FullName.Substring($repo.Length + 1)
    if ($errors) {
        $failed += $errors.Count
        Write-Host ("FAIL  {0}  ({1} errors)" -f $rel, $errors.Count) -ForegroundColor Red
        foreach ($e in $errors) {
            Write-Host ("        L{0}:{1}  {2}" -f $e.Extent.StartLineNumber, $e.Extent.StartColumnNumber, $e.Message)
        }
    } else {
        Write-Host ("OK    {0}" -f $rel) -ForegroundColor Green
    }
}
if ($failed -gt 0) {
    Write-Host ("`n{0} parse error(s) total." -f $failed) -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nAll PowerShell scripts parse cleanly." -ForegroundColor Cyan
}
'
