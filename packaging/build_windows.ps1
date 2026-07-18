# Build a complete Windows onedir + optional Inno Setup installer.
#
# Offline installers include Python, PySide6, and pinned vendor binaries
# (fpcalc) so the target PC needs no extra downloads.
#
# Usage (from repo root, PowerShell):
#   .\packaging\build_windows.ps1
#   .\packaging\build_windows.ps1 -SkipInstaller

param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..")

Write-Host "==> Fetching pinned vendor binaries"
python packaging/fetch_vendor.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> PyInstaller onedir"
pyinstaller packaging/musicvault.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$fpcalc = "dist\MusicVault\fpcalc.exe"
if (-not (Test-Path $fpcalc)) {
    Write-Error "Build missing $fpcalc — vendor binary was not collected"
    exit 1
}
Write-Host "Verified bundled $fpcalc"

if (-not $SkipInstaller) {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $guess = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $guess) { $iscc = Get-Item $guess }
    }
    if ($iscc) {
        Write-Host "==> Inno Setup installer"
        & $iscc.Source packaging\installer.iss
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "Installer: packaging\output\MusicVault-Setup.exe"
    }
    else {
        Write-Warning "ISCC not found — skipped installer (onedir is still in dist\MusicVault\)"
    }
}

Write-Host "Done."
