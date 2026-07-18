# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MusicVault (Windows onedir).

Build from repo root::

    python packaging/fetch_vendor.py
    pyinstaller packaging/musicvault.spec --noconfirm

Output: ``dist/MusicVault/`` (MusicVault.exe + Python deps + vendor
binaries such as ``fpcalc.exe``).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821
SRC = ROOT / "src"
VENDOR = ROOT / "packaging" / "vendor"

datas = []
binaries = []
hiddenimports = [
    "musicvault",
    "musicvault.__main__",
    "musicvault.gui.app",
    "musicvault.gui.main_window",
]

# Pinned native helpers (see packaging/vendor_manifest.json).
_fpcalc = VENDOR / "fpcalc.exe"
if not _fpcalc.is_file():
    raise SystemExit(
        f"Missing {_fpcalc}. Run: python packaging/fetch_vendor.py"
    )
binaries.append((str(_fpcalc), "."))

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
datas += pyside_datas
binaries += pyside_binaries
hiddenimports += list(pyside_hidden)

a = Analysis(  # noqa: F821
    [str(SRC / "musicvault" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MusicVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MusicVault",
)
