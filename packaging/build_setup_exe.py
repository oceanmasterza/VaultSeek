"""Build VaultSeek-Setup.exe — offline installer (no Inno Setup required).

Requires a finished PyInstaller onedir at ``dist/VaultSeek/``.

Creates ``packaging/output/VaultSeek-Setup.exe`` that:
  1. Installs the app under ``%LOCALAPPDATA%\\Programs\\VaultSeek``
  2. Writes ``Uninstall.exe`` + Start Menu uninstall shortcut
  3. Registers the app in Windows Apps & Features
  4. Optionally launches VaultSeek (default: No)

Usage (from repo root)::

    python packaging/fetch_vendor.py
    pyinstaller packaging/vaultseek.spec --noconfirm
    python packaging/build_setup_exe.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ONEDIR = _ROOT / "dist" / "VaultSeek"
_OUTPUT_DIR = _ROOT / "packaging" / "output"
_STAGING = _ROOT / "packaging" / "_setup_staging"
_SETUP_SCRIPT = Path(__file__).resolve().parent / "vaultseek_setup.py"


def _fpcalc_path() -> Path | None:
    """PyInstaller 6+ puts binaries under ``_internal/``; older layouts use onedir root."""
    for candidate in (_ONEDIR / "_internal" / "fpcalc.exe", _ONEDIR / "fpcalc.exe"):
        if candidate.is_file():
            return candidate
    return None


def _require_onedir() -> None:
    exe = _ONEDIR / "VaultSeek.exe"
    if not exe.is_file():
        raise SystemExit(f"Missing {exe}. Build with: pyinstaller packaging/vaultseek.spec")
    if _fpcalc_path() is None:
        raise SystemExit(
            f"Missing fpcalc.exe under {_ONEDIR} (or _internal/). "
            "Run: python packaging/fetch_vendor.py && rebuild"
        )
    if not _SETUP_SCRIPT.is_file():
        raise SystemExit(f"Missing installer script: {_SETUP_SCRIPT}")


def _zip_onedir(zip_path: Path) -> None:
    print(f"Zipping {_ONEDIR} -> {zip_path}")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in _ONEDIR.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(_ONEDIR).as_posix())
    print(f"  archive size: {zip_path.stat().st_size / (1024 * 1024):.1f} MiB")


def _run_pyinstaller(zip_path: Path, staging: Path) -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    script_copy = staging / "vaultseek_setup.py"
    shutil.copy2(_SETUP_SCRIPT, script_copy)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        "VaultSeek-Setup",
        "--distpath",
        str(_OUTPUT_DIR),
        "--workpath",
        str(staging / "build"),
        "--specpath",
        str(staging),
        f"--add-data={zip_path}{sep}.",
        str(script_copy),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=_ROOT)
    setup = _OUTPUT_DIR / "VaultSeek-Setup.exe"
    if not setup.is_file():
        raise SystemExit(f"Expected installer at {setup}")
    return setup


def main() -> int:
    _require_onedir()
    if _STAGING.exists():
        shutil.rmtree(_STAGING, ignore_errors=True)
    _STAGING.mkdir(parents=True, exist_ok=True)

    zip_path = _STAGING / "VaultSeekApp.zip"
    _zip_onedir(zip_path)
    setup = _run_pyinstaller(zip_path, _STAGING)
    size_mb = setup.stat().st_size / (1024 * 1024)
    print(f"\nInstaller ready: {setup} ({size_mb:.1f} MiB)")
    print("Install: double-click VaultSeek-Setup.exe")
    print("Uninstall: Start Menu > VaultSeek > Uninstall VaultSeek")
    print("         or Settings > Apps > VaultSeek > Uninstall")
    print("         or: Uninstall.exe --uninstall")
    print("Silent install: VaultSeek-Setup.exe --yes")
    print("Silent uninstall (keep data): Uninstall.exe --uninstall --yes")
    print("Silent uninstall + purge data: Uninstall.exe --uninstall --yes --purge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
