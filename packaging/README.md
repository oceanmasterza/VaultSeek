# Packaging MusicVault

MusicVault ships as a **self-contained Windows onedir** (and optional Inno
Setup installer). Python packages and pinned native helpers such as
**fpcalc** (Chromaprint) are bundled so a fresh PC does not need pip,
Chromaprint, or other downloads.

## Stable dependency pins

Third-party binaries are declared in
[`vendor_manifest.json`](vendor_manifest.json):

- **URL** — versioned GitHub Release asset
  (`…/releases/download/vX.Y.Z/…`). These URLs do not move when a newer
  Chromaprint is published.
- **SHA-256** — archive and extracted `.exe` hashes; `fetch_vendor.py`
  refuses to install on mismatch.

To upgrade a helper later: bump the versioned URL + hashes in the
manifest, re-run `fetch_vendor.py`, rebuild.

## Offline build (recommended)

```powershell
pip install -e ".[dev,build]"
.\packaging\build_windows.ps1
```

Or step by step:

```powershell
python packaging/fetch_vendor.py
pyinstaller packaging/musicvault.spec --noconfirm
# optional:
ISCC packaging\installer.iss
```

Outputs:

| Artifact | Path |
|----------|------|
| Portable app | `dist/MusicVault/` (`MusicVault.exe` + `fpcalc.exe` + deps) |
| Installer | `packaging/output/MusicVault-Setup.exe` |

The Inno script copies the **entire** `dist/MusicVault/` tree, so every
bundled dependency is installed under `{app}`.

## Online / repair download

If you only need to restore vendor binaries (e.g. after deleting
`fpcalc.exe`), re-run the same pinned fetch:

```powershell
python packaging/fetch_vendor.py --vendor-dir packaging\vendor
copy packaging\vendor\fpcalc.exe dist\MusicVault\fpcalc.exe
```

GitHub Release tags for **MusicVault itself** are also immutable:

```text
https://github.com/oceanmasterza/MusicVault/releases/download/v1.0.0/<asset>
```

Publish the onedir zip (or Setup.exe) as a release asset and keep the
tag forever; do not overwrite release assets in place.

## CI

The **Release** workflow on `v*.*.*` tags:

1. Runs the full test suite
2. Fetches vendor binaries (checksum verified)
3. Builds PyInstaller onedir
4. Uploads `dist/MusicVault/` as an artifact

## Headless / CI entry

```powershell
$env:MUSICVAULT_HEADLESS = "1"
python -m musicvault
```
