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
python -m PyInstaller packaging/vaultseek.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$fpcalc = $null
foreach ($candidate in @(
        "dist\VaultSeek\_internal\fpcalc.exe",
        "dist\VaultSeek\fpcalc.exe"
    )) {
    if (Test-Path $candidate) {
        $fpcalc = $candidate
        break
    }
}
if (-not $fpcalc) {
    Write-Error "Build missing fpcalc.exe under dist\VaultSeek\ - vendor binary was not collected"
    exit 1
}
Write-Host "Verified bundled $fpcalc"

if (-not $SkipInstaller) {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        foreach ($guess in @(
                "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
                "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
            )) {
            if (Test-Path $guess) {
                $iscc = Get-Item $guess
                break
            }
        }
    }
    if ($iscc) {
        Write-Host "==> Inno Setup installer"
        & $iscc.Source packaging\installer.iss
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "Installer: packaging\output\VaultSeek-Setup.exe"
    }
    else {
        Write-Host "==> Python Setup.exe (ISCC not found)"
        python packaging/build_setup_exe.py
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

Write-Host "Done."
