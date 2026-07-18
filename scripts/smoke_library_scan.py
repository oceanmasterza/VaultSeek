"""End-to-end library smoke test against a folder of audio files.

Creates a temporary MusicVault data dir + four zone folders, optionally
generates a few tagged WAV samples, enqueues ``scan_directory``, waits for
the job queue to drain, and prints a pipeline report.

Usage::

    # Generate 3 sample WAVs under ./samples/incoming and scan them
    python scripts/smoke_library_scan.py

    # Scan your own folder (copied into Incoming for the run)
    python scripts/smoke_library_scan.py --music-dir "D:\\Music\\Incoming"

    # Keep the temp data dir for GUI inspection afterward
    python scripts/smoke_library_scan.py --keep

Requires ``fpcalc`` on PATH (or ``tools/fpcalc.exe``) for fingerprint →
identify to complete. Without it, scan + hash still run; fingerprint jobs
fail and metadata is not reached unless ``--force-identify`` is set.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import struct
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from mutagen.wave import WAVE

# Ensure src/ is importable when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from musicvault.app import bootstrap  # noqa: E402
from musicvault.models.entities.job import JobStatus, JobType  # noqa: E402
from musicvault.models.entities.library import Library  # noqa: E402
from musicvault.models.entities.track import LibraryZone  # noqa: E402


_SAMPLE_TRACKS = (
    ("Demo Artist", "Demo Album", "Morning Light", 1),
    ("Demo Artist", "Demo Album", "Night Drive", 2),
    ("Other Band", "B-Sides", "Untitled Sketch", 1),
)


def _ensure_fpcalc_on_path(root: Path) -> str | None:
    from musicvault.core.native_bins import configure_native_bin_path

    # Prefer repo tools/ then packaging/vendor/ via the shared helper.
    os.environ.setdefault("PATH", "")
    tools = root / "tools" / "fpcalc.exe"
    if tools.is_file():
        os.environ["FPCALC"] = str(tools)
    found = configure_native_bin_path()
    return str(found) if found is not None else None


def _write_tone_wav(path: Path, *, frequency_hz: float, seconds: float = 3.0) -> None:
    """Write a short mono 16-bit WAV (audible tone) for scanner/hash tests."""
    rate = 44100
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            value = int(16000 * math.sin(2 * math.pi * frequency_hz * (i / rate)))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(frames)


def _tag_wav(path: Path, *, artist: str, album: str, title: str, track_number: int) -> None:
    from mutagen.id3 import TALB, TIT2, TPE1, TRCK

    audio = WAVE(str(path))
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags.delall("TIT2")
    audio.tags.delall("TPE1")
    audio.tags.delall("TALB")
    audio.tags.delall("TRCK")
    audio.tags.add(TIT2(encoding=3, text=[title]))
    audio.tags.add(TPE1(encoding=3, text=[artist]))
    audio.tags.add(TALB(encoding=3, text=[album]))
    audio.tags.add(TRCK(encoding=3, text=[str(track_number)]))
    audio.save()


def generate_samples(incoming: Path) -> list[Path]:
    paths: list[Path] = []
    for index, (artist, album, title, track_no) in enumerate(_SAMPLE_TRACKS):
        safe = f"{track_no:02d} - {title}.wav"
        dest = incoming / artist / album / safe
        _write_tone_wav(dest, frequency_hz=220.0 * (index + 1))
        _tag_wav(dest, artist=artist, album=album, title=title, track_number=track_no)
        paths.append(dest)
    return paths


def copy_music_dir(source: Path, incoming: Path) -> int:
    count = 0
    exts = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".wv"}
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts:
            rel = path.relative_to(source)
            dest = incoming / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            count += 1
    return count


def _wait_for_idle(container: object, library_id: object, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stats = container.job_queue.get_stats(library_id)  # type: ignore[attr-defined]
        active = stats.pending + stats.running
        if active == 0:
            # Also wait for retries to drain
            retry = container.job_repo.list_by_status(  # type: ignore[attr-defined]
                JobStatus.RETRY, library_id=library_id, limit=1
            )
            if not retry:
                return
        time.sleep(0.4)
    raise TimeoutError(f"Pipeline still busy after {timeout:.0f}s")


def _print_report(container: object, library_id: object) -> None:
    tracks = list(container.track_repo.get_by_library(library_id, limit=500))  # type: ignore[attr-defined]
    zones = container.track_repo.count_by_zone(library_id)  # type: ignore[attr-defined]
    pending_review = container.review_queue.count_pending(library_id)  # type: ignore[attr-defined]
    stats = container.job_queue.get_stats(library_id)  # type: ignore[attr-defined]
    failed = container.job_repo.list_by_status(  # type: ignore[attr-defined]
        JobStatus.FAILED, library_id=library_id, limit=20
    )

    print("\n=== Smoke report ===")
    print(f"Tracks: {len(tracks)}  zones={zones}")
    print(
        f"Jobs: pending={stats.pending} running={stats.running} "
        f"failed={stats.failed} completed_today={stats.completed_today}"
    )
    print(f"Review pending: {pending_review}")
    for track in tracks:
        title = track.title or "(no title)"
        print(
            f"  - [{track.zone.value}] {title}  "
            f"conf={track.overall_confidence}  needs_review={track.needs_review}  "
            f"file={Path(track.file_path).name}"
        )
    if failed:
        print("Failed jobs:")
        for job in failed:
            print(f"  - {job.job_type.value}: {job.error_message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--music-dir",
        type=Path,
        help="Existing folder of audio files to copy into Incoming (default: generate samples)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not delete the temp data/library dirs; print their paths",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the job queue to go idle (default: 120)",
    )
    parser.add_argument(
        "--force-identify",
        action="store_true",
        help="After idle, enqueue identify_metadata for every track (useful without fpcalc)",
    )
    args = parser.parse_args(argv)

    fpcalc = _ensure_fpcalc_on_path(_ROOT)
    print(f"fpcalc: {fpcalc or 'NOT FOUND (fingerprint stage will fail)'}")

    work = _ROOT / "temp" / f"smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    data_dir = work / "appdata"
    library_root = work / "library"
    incoming = library_root / "Incoming"
    staging = library_root / "Staging"
    library_path = library_root / "Music"
    archive = library_root / "Archive"
    for path in (incoming, staging, library_path, archive):
        path.mkdir(parents=True, exist_ok=True)

    if args.music_dir is not None:
        source = args.music_dir.expanduser().resolve()
        if not source.is_dir():
            print(f"Music dir not found: {source}", file=sys.stderr)
            return 2
        n = copy_music_dir(source, incoming)
        print(f"Copied {n} audio file(s) from {source}")
        if n == 0:
            print("No audio files found to scan.", file=sys.stderr)
            return 2
    else:
        paths = generate_samples(incoming)
        print(f"Generated {len(paths)} sample WAV(s) under {incoming}")

    container = bootstrap(base_dir_override=data_dir, console_logging=True)
    try:
        now = datetime.now(UTC)
        library = Library(
            id=uuid7(),
            name="Smoke Library",
            incoming_path=str(incoming),
            staging_path=str(staging),
            library_path=str(library_path),
            archive_path=str(archive),
            created_at=now,
            updated_at=now,
            watch_enabled=False,
        )
        container.library_repo.upsert(library)
        print(f"Library id={library.id}")

        container.job_queue.enqueue(
            JobType.SCAN_DIRECTORY,
            library.id,
            {"directory": str(incoming), "zone": LibraryZone.INCOMING.value},
            now=now,
        )
        print("Enqueued scan_directory — waiting for idle…")
        _wait_for_idle(container, library.id, timeout=args.timeout)

        if args.force_identify or fpcalc is None:
            tracks = list(container.track_repo.get_by_library(library.id, limit=500))
            print(f"Force-enqueue identify_metadata for {len(tracks)} track(s)")
            for track in tracks:
                container.job_queue.enqueue(
                    JobType.IDENTIFY_METADATA,
                    library.id,
                    {"track_id": str(track.id)},
                )
            _wait_for_idle(container, library.id, timeout=args.timeout)

        _print_report(container, library.id)
    finally:
        container.close()

    if args.keep:
        print(f"\nKept work dir: {work}")
        print(f"Data dir:      {data_dir}")
        print(f"Library root:  {library_root}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        print("\nCleaned temp work dir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
