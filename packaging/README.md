# Packaging MusicVault

## PyInstaller (required for releases)

```powershell
pip install -e ".[dev,build]"
pyinstaller packaging/musicvault.spec --noconfirm
```

Produces `dist/MusicVault/MusicVault.exe` (onedir). The GitHub Actions
**Release** workflow runs this on `v*.*.*` tags and uploads the folder as
an artifact.

Headless / CI entry (no GUI):

```powershell
$env:MUSICVAULT_HEADLESS = "1"
python -m musicvault
# or: python -m musicvault --headless
```

## Windows installer (optional)

1. Build the PyInstaller bundle (above).
2. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
3. Compile `packaging/installer.iss` (or run `ISCC packaging\installer.iss`).

Output: `packaging/output/MusicVault-Setup.exe`.
