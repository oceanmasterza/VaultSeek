# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VaultSeek (Windows onedir).

Build from repo root::

    python packaging/fetch_vendor.py
    pyinstaller packaging/vaultseek.spec --noconfirm

Output: ``dist/VaultSeek/`` (VaultSeek.exe + Python deps + vendor
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
    "vaultseek",
    "vaultseek.__main__",
    "vaultseek.gui.app",
    "vaultseek.gui.main_window",
    "logging.config",
    "alembic",
    "alembic.runtime.migration",
    "alembic.runtime.environment",
]

# Pinned native helpers (see packaging/vendor_manifest.json).
_fpcalc = VENDOR / "fpcalc.exe"
if not _fpcalc.is_file():
    raise SystemExit(
        f"Missing {_fpcalc}. Run: python packaging/fetch_vendor.py"
    )
binaries.append((str(_fpcalc), "."))

# Alembic needs the migrations tree on disk (not only inside the PYZ).
_migrations = SRC / "vaultseek" / "db" / "migrations"
datas.append((str(_migrations), "vaultseek/db/migrations"))

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
datas += pyside_datas
binaries += pyside_binaries
hiddenimports += list(pyside_hidden)

# Shazamio + native core (and numpy) for in-process audio recognition fallback.
for _pkg in ("shazamio", "shazamio_core", "numpy"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += list(_h)

a = Analysis(  # noqa: F821
    [str(SRC / "vaultseek" / "__main__.py")],
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
    name="VaultSeek",
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
    name="VaultSeek",
)
