"""Download and verify pinned native binaries for Windows packaging.

Reads ``packaging/vendor_manifest.json``, downloads each archive from its
versioned (immutable) GitHub release URL, verifies SHA-256, extracts the
named member into ``packaging/vendor/``.

Usage (from repo root)::

    python packaging/fetch_vendor.py
    python packaging/fetch_vendor.py --vendor-dir packaging/vendor

Exit codes: 0 success, 1 verification/download failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

_DEFAULT_MANIFEST = Path(__file__).resolve().parent / "vendor_manifest.json"
_DEFAULT_VENDOR = Path(__file__).resolve().parent / "vendor"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str) -> bytes:
    with urlopen(url, timeout=120) as response:  # noqa: S310 - pinned HTTPS URLs from manifest
        return response.read()


def fetch_all(*, manifest_path: Path, vendor_dir: Path) -> list[Path]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    binaries = document.get("binaries")
    if not isinstance(binaries, list) or not binaries:
        raise SystemExit(f"No binaries listed in {manifest_path}")

    vendor_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []

    for entry in binaries:
        binary_id = entry["id"]
        url = entry["url"]
        expected_zip = str(entry["sha256"]).lower()
        install_as = entry["install_as"]
        member = entry["extract_member"]
        expected_exe = str(entry.get("exe_sha256", "")).lower()
        dest = vendor_dir / install_as

        print(f"Fetching {binary_id} from {url}")
        try:
            payload = _download(url)
        except URLError as exc:
            raise SystemExit(f"Download failed for {binary_id}: {exc}") from exc

        actual_zip = _sha256(payload)
        if actual_zip != expected_zip:
            raise SystemExit(
                f"SHA-256 mismatch for {binary_id} archive:\n"
                f"  expected {expected_zip}\n"
                f"  actual   {actual_zip}"
            )

        if entry.get("archive") != "zip":
            raise SystemExit(f"Unsupported archive type for {binary_id}")

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "download.zip"
            zip_path.write_bytes(payload)
            with zipfile.ZipFile(zip_path) as archive:
                if member not in archive.namelist():
                    raise SystemExit(f"{binary_id}: member {member!r} not in archive")
                exe_bytes = archive.read(member)

        if expected_exe:
            actual_exe = _sha256(exe_bytes)
            if actual_exe != expected_exe:
                raise SystemExit(
                    f"SHA-256 mismatch for {binary_id} executable:\n"
                    f"  expected {expected_exe}\n"
                    f"  actual   {actual_exe}"
                )

        dest.write_bytes(exe_bytes)
        print(f"  -> {dest} ({len(exe_bytes)} bytes, verified)")
        installed.append(dest)

    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_DEFAULT_MANIFEST,
        help="Path to vendor_manifest.json",
    )
    parser.add_argument(
        "--vendor-dir",
        type=Path,
        default=_DEFAULT_VENDOR,
        help="Directory to write extracted binaries into",
    )
    args = parser.parse_args(argv)
    if not args.manifest.is_file():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    paths = fetch_all(manifest_path=args.manifest, vendor_dir=args.vendor_dir)
    print(f"Vendor ready: {len(paths)} binary(ies) in {args.vendor_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
