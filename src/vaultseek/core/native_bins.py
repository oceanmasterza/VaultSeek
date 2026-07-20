"""Locate bundled native helpers (fpcalc, …) for frozen and source runs.

PyInstaller 6 onedir ships verified binaries under ``_internal/``
(``sys._MEIPASS`` when frozen). Older layouts may place ``fpcalc.exe``
next to ``VaultSeek.exe``. See ``packaging/vaultseek.spec`` and
``packaging/vendor_manifest.json``.

Dev checkouts may use ``tools/fpcalc.exe`` or ``packaging/vendor/fpcalc.exe``.

Call :func:`configure_native_bin_path` once at process start so pyacoustid
finds ``fpcalc`` via ``PATH`` / ``FPCALC``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def application_dir() -> Path:
    """Directory that contains the running executable or project root tools."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # src/vaultseek/core/native_bins.py → repo root
    return Path(__file__).resolve().parents[3]


def find_fpcalc() -> Path | None:
    """Return the preferred ``fpcalc`` executable, or ``None`` if missing."""
    candidates: list[Path] = []
    env = os.environ.get("FPCALC") or os.environ.get("FPCALC_COMMAND")
    if env:
        candidates.append(Path(env))

    # Frozen onedir: binaries live in _MEIPASS (_internal) with PyInstaller 6+.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "fpcalc.exe")
        candidates.append(Path(meipass) / "fpcalc")

    app = application_dir()
    candidates.extend(
        [
            app / "fpcalc.exe",
            app / "fpcalc",
            app / "_internal" / "fpcalc.exe",
            app / "tools" / "fpcalc.exe",
            app / "packaging" / "vendor" / "fpcalc.exe",
        ]
    )
    # When running from an editable install, application_dir is repo root.
    # Also check next to this package for a copied vendor tree.
    here = Path(__file__).resolve().parent
    candidates.append(here / "vendor" / "fpcalc.exe")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def configure_native_bin_path() -> Path | None:
    """Put bundled ``fpcalc`` on ``PATH`` and set ``FPCALC`` when found.

    Returns the path that was configured, or ``None`` if nothing was found
    (fingerprint jobs will then fail with a clear backend error).
    """
    fpcalc = find_fpcalc()
    if fpcalc is None:
        return None
    os.environ["FPCALC"] = str(fpcalc)
    os.environ["FPCALC_COMMAND"] = str(fpcalc)
    bin_dir = str(fpcalc.parent)
    path = os.environ.get("PATH", "")
    if bin_dir not in path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + path
    return fpcalc
