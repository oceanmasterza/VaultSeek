"""Built-in Chromaprint fingerprint provider (via pyacoustid / fpcalc).

AcoustID *HTTP* lookup is deferred to Phase 6 (MetadataWorker). This
module only generates Chromaprint bytes for :class:`FingerprintWorker`.

Stock pyacoustid launches ``fpcalc`` without ``CREATE_NO_WINDOW``, which
flashes a console on every track on Windows. We patch that helper once
before calling :func:`acoustid.fingerprint_file`.
"""

from __future__ import annotations

import errno
import hashlib
import os
import subprocess
from pathlib import Path

import acoustid

from vaultseek.models.interfaces.fingerprint import FingerprintResult

_CREATE_NO_WINDOW = 0x08000000
_PATCHED_ATTR = "_vaultseek_fpcalc_no_window"


def _fingerprint_file_fpcalc_hidden(path: str, maxlength: float) -> tuple[float, bytes]:
    """Same contract as ``acoustid._fingerprint_file_fpcalc``, without a console."""
    fpcalc = os.environ.get(acoustid.FPCALC_ENVVAR, acoustid.FPCALC_COMMAND)
    command = [fpcalc, "-length", str(maxlength), path]
    kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
        output, _ = proc.communicate()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise acoustid.NoBackendError("fpcalc not found") from exc
        raise acoustid.FingerprintGenerationError(
            f"fpcalc invocation failed: {exc}"
        ) from exc
    if proc.returncode:
        raise acoustid.FingerprintGenerationError(
            f"fpcalc exited with status {proc.returncode}"
        )

    duration: float | None = None
    fingerprint: bytes | None = None
    for line in output.splitlines():
        parts = line.split(b"=", 1)
        if len(parts) != 2:
            continue
        if parts[0] == b"DURATION":
            try:
                duration = float(parts[1])
            except ValueError as exc:
                raise acoustid.FingerprintGenerationError(
                    "fpcalc duration not numeric"
                ) from exc
        elif parts[0] == b"FINGERPRINT":
            fingerprint = parts[1]

    if duration is None or fingerprint is None:
        raise acoustid.FingerprintGenerationError("missing fpcalc output")
    return duration, fingerprint


def _ensure_fpcalc_no_window() -> None:
    if getattr(acoustid, _PATCHED_ATTR, False):
        return
    acoustid._fingerprint_file_fpcalc = _fingerprint_file_fpcalc_hidden  # type: ignore[attr-defined]
    setattr(acoustid, _PATCHED_ATTR, True)


def generate_chromaprint(path: Path) -> FingerprintResult:
    """Run Chromaprint against ``path`` and return a typed result."""
    _ensure_fpcalc_no_window()
    absolute = str(path.resolve())
    try:
        duration, fingerprint = acoustid.fingerprint_file(absolute)
    except acoustid.NoBackendError as exc:
        raise RuntimeError(
            "Chromaprint backend not found — install fpcalc or the chromaprint library"
        ) from exc
    except acoustid.FingerprintGenerationError as exc:
        raise RuntimeError(f"Chromaprint failed for {path}: {exc}") from exc

    if isinstance(fingerprint, bytes):
        fingerprint_data = fingerprint
    else:
        fingerprint_data = str(fingerprint).encode("utf-8")

    return FingerprintResult(
        duration_seconds=float(duration),
        fingerprint_data=fingerprint_data,
        fingerprint_hash=hashlib.sha256(fingerprint_data).hexdigest(),
    )


class ChromaprintFingerprintProvider:
    """:class:`~vaultseek.models.interfaces.fingerprint.FingerprintProvider`
    implementation that wraps :func:`generate_chromaprint`."""

    def fingerprint_file(self, path: Path) -> FingerprintResult:
        return generate_chromaprint(path)
