"""Unit tests for collision-safe atomic tag writes."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

import pytest
from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

from vaultseek.services.tag_writer import TagWriteRequest, write_embedded_tags

# zlib-compressed mutagen samples (lame397v9short.mp3, no-tags.flac, no-tags.m4a).
_MP3_Z = (
    "eNr7/7klhQEdRGTmpQMpfiBmZmBg0mBQIgRWEQL/CQGgXew+jr6uxnqW5grMYDfpTGBgEOFQYV3j"
    "y8A4C+SOWdeTa9Cc+v+zSgoDYwpjxJoFHAzMCkxLIx0EGBgOmMgvB5r57zwPRwITz+7r7iAbHvyS"
    "Pqnx/3OLCzNbx+yAijMyDNIf66Z8nF3BwJHB3HbyYE/qgRkbTlXwbRG5ufhzmPqjzyEONrI7HVc+"
    "EfnxkKVvsxjQD9v//+UR4mx52uBlwCzEkJC0zIsrXYjNTCTD+JmGxYGjDpGCHIyGK15otRu7TObg"
    "T/QpYTLwXzvFScrvmLKkdVOsYI9/4ycbfmFh/4hn+3bLzfsfPzv93MPwX0v6fLc2vZb+//a1kIRM"
    "m5Vp3dZNu6Tv/vfN/7kmJf7/j8mvmLgUGk6wMjAISP//HOLCxTxFPuHMoR4GIUG7NYYTHRjMDPSP"
    "9WleevLzeF3Iew2J+h8MJ2ad1WC8YbHJojm5wGq5T+EqQ3aT4oI/6raz/9iICLK/Cfl/7OmOFauN"
    "6x81tcn/Flm0aP//nYea2rg7+mvsHjU0WAmxtaz99GzLXV1YlAAAvp7p0A=="
)
_FLAC_Z = (
    "eNrt0M8rw3Ecx/GPbczG5utrZphh28UQUn6U0iZyWCEOLD8abRIHJ78OatlSuPtxw8lBcZM0Cgct"
    "uUm5uSmHkdjJePXawR/xeV7e70e9T++wP9glhHCqQv0bZiEU440vKTQrV/un3u/wa3Tv+llpPDB2"
    "LEaEUidkMplMJpPJZDKZTCaTyf6VTo3YxCx3ZQPKmqPW05AmRMVDkHaSqlEg3SJ1PwBlz1MBN5Sz"
    "TE3FIf0q9ZmAcgep2nbIMERd+CHjGBV7hPIClHoI5fdRXy+QqZcKbkNmLzVsggp6qIclSCmnpt+g"
    "QjuV3IXUYupOCxWp1PgCZNFT561Q5lDU+yCrgbI8QSVmau0Ysrmo0Qmo1E0lPFBZPfVxApV7qNAt"
    "ZO+kIlGooo2yvkOOJqphFqpsoc4cUNUm9dMDVW9RM82QM0b1H6VTyzaX7nIn86fuX9lRlVs="
)
_M4A_Z = (
    "eNrtVr1Lw1AQv6StVhQsfuDnED8GBxGs/QNatYogCCK4CJL2JRrMa2rea0EH6e5S0F3Xgv+Ag9jN"
    "v8BBB2f/APd6Z1J9KghOOuTIcb873st9cHcJAAzb8qjMy5k0IJF0hMcBEtecmfIpDuA6Bds0i8b8"
    "XDoDsAhnRjwNqxOwVtdHYKoWgQhEIAIR+A8Ad3iSFjcu8CT3vCrqLq/uM1ruzZf8Q/Nl/Ra03Tok"
    "hvpBA3o+6JPyXc/Cj6QjDzseE6SkarVaJ2y0Wr2tFkBcSt88QPOOPHiLRQtiyT++e6F4vrr+VTzx"
    "FGeOicDgTM2XfFwtg37SDA9O7DPXb98SXqX0xUvsjjslm3IQPHhRSNMssI8z37KVkHoqvmsEOHYq"
    "ZMFFvCekYMqZbfyymt/S0CFFAsMjWrBEULwYFm+SUkI5kB0EGEUnzwDdhQRa9L5UBwqN6m0IKYVS"
    "/wu8FLrQMV/9HMM4VlK4hLeXQVfEEf8Rz2BPFpWepXGYDSU173iIsbeLXnu4SUfzDQ7HGqr3pBc/"
    "974W9v5FaEtWmKSRO7R9y1JnHveEb5bLrjr0644rJC2HhvTI6QjuULM9qyu53FL4+wtTjdzmFsox"
    "9cCWJaSR86Uj5CsM1JSY"
)


def _write_fixture(path: Path, compressed_b64: str) -> Path:
    path.write_bytes(zlib.decompress(base64.b64decode(compressed_b64)))
    return path


def _audio_payload_hash(path: Path) -> str:
    """Hash audio bytes with common tag containers stripped (MP3 ID3/TAG)."""
    data = path.read_bytes()
    if data[:3] == b"ID3":
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        data = data[10 + size :]
    if len(data) >= 128 and data[-128:-125] == b"TAG":
        data = data[:-128]
    return hashlib.sha256(data).hexdigest()


def _stream_fingerprint(path: Path) -> tuple[object, ...]:
    """Format-agnostic audio stream identity (length / rate / channels)."""
    audio = MutagenFile(str(path))
    assert audio is not None and audio.info is not None
    info = audio.info
    return (
        round(float(getattr(info, "length", 0.0)), 4),
        getattr(info, "sample_rate", None),
        getattr(info, "channels", None),
        getattr(info, "bits_per_sample", None),
        getattr(info, "bitrate", None),
    )


def _seed_unrelated_mp3(path: Path) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(APIC(mime="image/png", type=3, desc="cover", data=b"cover-bytes"))
    tags.add(COMM(encoding=3, lang="eng", desc="note", text=["keep-comment"]))
    tags.save(path)
    audio = MutagenFile(str(path), easy=True)
    assert audio is not None
    audio["genre"] = ["Rock"]
    audio.save()


def _seed_unrelated_flac(path: Path) -> None:
    audio = FLAC(str(path))
    picture = Picture()
    picture.type = 3
    picture.mime = "image/png"
    picture.desc = "cover"
    picture.data = b"cover-bytes"
    audio.add_picture(picture)
    audio["comment"] = ["keep-comment"]
    audio["genre"] = ["Rock"]
    audio.save()


def _seed_unrelated_m4a(path: Path) -> None:
    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags["\xa9cmt"] = ["keep-comment"]
    audio.tags["\xa9gen"] = ["Rock"]
    audio.tags["covr"] = [MP4Cover(b"cover-bytes", imageformat=MP4Cover.FORMAT_PNG)]
    audio.save()


@pytest.fixture
def backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated APPDATA backup root — never touches the real profile."""
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    dedicated = tmp_path / "tag-backups"
    dedicated.mkdir()
    return dedicated


def _backup_file_count(backup_dir: Path) -> int:
    return len([p for p in backup_dir.iterdir() if p.suffix == ".bak"])


@pytest.mark.parametrize(
    ("suffix", "blob", "seed"),
    [
        (".mp3", _MP3_Z, _seed_unrelated_mp3),
        (".flac", _FLAC_Z, _seed_unrelated_flac),
        (".m4a", _M4A_Z, _seed_unrelated_m4a),
    ],
)
def test_writes_identity_tags_preserving_unrelated_metadata(
    tmp_path: Path,
    backup_dir: Path,
    suffix: str,
    blob: str,
    seed: object,
) -> None:
    target = _write_fixture(tmp_path / f"track{suffix}", blob)
    seed(target)  # type: ignore[operator]
    before_stream = _stream_fingerprint(target)
    before_mp3_hash = _audio_payload_hash(target) if suffix == ".mp3" else None
    before_bytes = target.read_bytes()

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(
            title="Soul Messiah",
            artist="Alphaville",
            album="Salvation",
            track_number=10,
            disc_number=1,
            year=2023,
        ),
        backup_dir=backup_dir,
    )

    assert result.wrote is True
    assert result.changed is True
    assert result.error is None
    assert result.backup_path is not None
    backup = Path(result.backup_path)
    assert backup.is_file()
    assert backup.read_bytes() == before_bytes

    easy = MutagenFile(str(target), easy=True)
    assert easy is not None
    assert list(easy["title"]) == ["Soul Messiah"]
    assert list(easy["artist"]) == ["Alphaville"]
    assert list(easy["album"]) == ["Salvation"]
    assert list(easy["tracknumber"]) == ["10"]
    assert list(easy["discnumber"]) == ["1"]
    assert list(easy["date"]) == ["2023"]
    assert _stream_fingerprint(target) == before_stream
    if before_mp3_hash is not None:
        assert _audio_payload_hash(target) == before_mp3_hash

    if suffix == ".mp3":
        tags = ID3(target)
        assert tags.getall("APIC")[0].data == b"cover-bytes"
        assert tags.getall("COMM")[0].text == ["keep-comment"]
        assert list(easy["genre"]) == ["Rock"]
    elif suffix == ".flac":
        flac = FLAC(str(target))
        assert flac.pictures[0].data == b"cover-bytes"
        assert flac["comment"] == ["keep-comment"]
        assert list(easy["genre"]) == ["Rock"]
    else:
        mp4 = MP4(str(target))
        assert mp4.tags is not None
        assert bytes(mp4.tags["covr"][0]) == b"cover-bytes"
        assert mp4.tags["\xa9cmt"] == ["keep-comment"]
        assert list(easy["genre"]) == ["Rock"]


def test_backup_paths_collide_proof_same_basename_same_second(
    tmp_path: Path, backup_dir: Path
) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _write_fixture(first_dir / "song.mp3", _MP3_Z)
    second = _write_fixture(second_dir / "song.mp3", _MP3_Z)
    first_bytes = first.read_bytes()
    second_bytes = second.read_bytes()

    result_a = write_embedded_tags(
        str(first),
        TagWriteRequest(title="One"),
        backup_dir=backup_dir,
    )
    result_b = write_embedded_tags(
        str(second),
        TagWriteRequest(title="Two"),
        backup_dir=backup_dir,
    )

    assert result_a.wrote and result_b.wrote
    assert result_a.backup_path != result_b.backup_path
    backup_a = Path(result_a.backup_path or "")
    backup_b = Path(result_b.backup_path or "")
    assert backup_a.is_file() and backup_b.is_file()
    assert backup_a.read_bytes() == first_bytes
    assert backup_b.read_bytes() == second_bytes

    meta_a = json.loads(Path(f"{backup_a}.source.json").read_text(encoding="utf-8"))
    meta_b = json.loads(Path(f"{backup_b}.source.json").read_text(encoding="utf-8"))
    assert Path(meta_a["source_path"]) == first.resolve()
    assert Path(meta_b["source_path"]) == second.resolve()


def test_repeated_writes_same_second_keep_distinct_backups(
    tmp_path: Path, backup_dir: Path
) -> None:
    """Different requests still allocate unique backups even in the same second."""
    target = _write_fixture(tmp_path / "repeat.mp3", _MP3_Z)
    paths: set[str] = set()
    for index in range(3):
        result = write_embedded_tags(
            str(target),
            TagWriteRequest(title=f"Title {index}"),
            backup_dir=backup_dir,
        )
        assert result.wrote is True
        assert result.changed is True
        assert result.backup_path is not None
        paths.add(result.backup_path)
        assert Path(result.backup_path).is_file()
    assert len(paths) == 3


def test_idempotent_same_request_skips_backup_and_mtime(tmp_path: Path, backup_dir: Path) -> None:
    target = _write_fixture(tmp_path / "stable.mp3", _MP3_Z)
    request = TagWriteRequest(
        title="Soul Messiah",
        artist="Alphaville",
        album="Salvation",
        track_number=10,
        disc_number=1,
        year=2023,
    )
    first = write_embedded_tags(str(target), request, backup_dir=backup_dir)
    assert first.wrote is True
    assert first.changed is True
    assert first.backup_path is not None

    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    backups_before = _backup_file_count(backup_dir)

    second = write_embedded_tags(str(target), request, backup_dir=backup_dir)
    assert second.wrote is True
    assert second.changed is False
    assert second.backup_path is None
    assert second.error is None
    assert target.read_bytes() == before_bytes
    assert target.stat().st_mtime_ns == before_mtime
    assert _backup_file_count(backup_dir) == backups_before


def test_concurrent_source_modification_fails_closed(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vaultseek.services.tag_writer as tag_writer

    target = _write_fixture(tmp_path / "race.mp3", _MP3_Z)
    original_snapshot = tag_writer._file_snapshot
    first_call = True

    def snapshot_then_mutate(path: Path) -> tuple[int, int]:
        nonlocal first_call
        snap = original_snapshot(path)
        if first_call:
            first_call = False
            # Concurrent editor changes tags after our snapshot.
            other = MutagenFile(str(path), easy=True)
            assert other is not None
            other["title"] = ["Concurrent Edit"]
            other.save()
        return snap

    monkeypatch.setattr(tag_writer, "_file_snapshot", snapshot_then_mutate)

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(title="Our Write"),
        backup_dir=backup_dir,
    )

    assert result.wrote is False
    assert result.changed is False
    assert result.error == "source modified during tag write"
    assert list(tmp_path.glob(".*.tagwrite-*")) == []
    easy = MutagenFile(str(target), easy=True)
    assert easy is not None
    assert list(easy["title"]) == ["Concurrent Edit"]


def test_unsupported_format_cleans_temp_and_does_not_restore(
    tmp_path: Path, backup_dir: Path
) -> None:
    target = tmp_path / "notes.txt"
    original = b"not-an-audio-file"
    target.write_bytes(original)

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(title="Nope"),
        backup_dir=backup_dir,
    )

    assert result.wrote is False
    assert result.error == "unsupported format"
    assert result.backup_path is None
    assert target.read_bytes() == original
    leftovers = list(tmp_path.glob(".*.tagwrite-*"))
    assert leftovers == []
    assert _backup_file_count(backup_dir) == 0


def test_failure_before_replace_does_not_clobber_target(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_fixture(tmp_path / "safe.mp3", _MP3_Z)
    original = target.read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("mutagen save failed")

    from mutagen import File as MutagenFileOriginal

    def fake_file(path: str, *args: object, **kwargs: object) -> object:
        audio = MutagenFileOriginal(path, *args, **kwargs)
        if audio is not None:
            monkeypatch.setattr(audio, "save", boom, raising=False)
        return audio

    monkeypatch.setattr("mutagen.File", fake_file)

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(title="Fail"),
        backup_dir=backup_dir,
    )

    assert result.wrote is False
    assert result.error is not None
    assert "mutagen save failed" in (result.error or "")
    assert target.read_bytes() == original
    assert list(tmp_path.glob(".*.tagwrite-*")) == []


def test_empty_and_invalid_requests_fail_closed(tmp_path: Path, backup_dir: Path) -> None:
    target = _write_fixture(tmp_path / "valid.mp3", _MP3_Z)
    original = target.read_bytes()

    empty = write_embedded_tags(str(target), TagWriteRequest(), backup_dir=backup_dir)
    assert empty.wrote is False
    assert empty.error == "empty tag request"
    assert target.read_bytes() == original

    blank = write_embedded_tags(str(target), TagWriteRequest(title="   "), backup_dir=backup_dir)
    assert blank.wrote is False
    assert blank.error == "invalid title"
    assert target.read_bytes() == original

    bad_track = write_embedded_tags(
        str(target),
        TagWriteRequest(title="Ok", track_number=0),
        backup_dir=backup_dir,
    )
    assert bad_track.wrote is False
    assert bad_track.error == "invalid track_number"
    assert target.read_bytes() == original

    bad_year = write_embedded_tags(
        str(target),
        TagWriteRequest(title="Ok", year=99),
        backup_dir=backup_dir,
    )
    assert bad_year.wrote is False
    assert bad_year.error == "invalid year"
    assert target.read_bytes() == original
    assert list(backup_dir.iterdir()) == []


def test_missing_file_fails_without_backup(backup_dir: Path) -> None:
    missing = backup_dir / "gone.mp3"
    result = write_embedded_tags(
        str(missing),
        TagWriteRequest(title="X"),
        backup_dir=backup_dir,
    )
    assert result.wrote is False
    assert result.error == "file missing"
    assert result.backup_path is None


def test_corrupt_reader_fails_closed(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "corrupt.mp3"
    target.write_bytes(b"not-a-valid-mpeg-payload")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("mutagen corrupt header")

    monkeypatch.setattr("mutagen.File", boom)

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(title="X"),
        backup_dir=backup_dir,
    )

    assert result.wrote is False
    assert result.changed is False
    assert result.backup_path is None
    assert "mutagen corrupt header" in (result.error or "")
    assert target.read_bytes() == b"not-a-valid-mpeg-payload"
    assert _backup_file_count(backup_dir) == 0
    assert list(tmp_path.glob(".*.tagwrite-*")) == []


def test_disappearing_source_fails_closed(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mutagen import File as MutagenFileOriginal

    target = _write_fixture(tmp_path / "vanish.mp3", _MP3_Z)

    def open_then_vanish(path: str, *args: object, **kwargs: object) -> object:
        audio = MutagenFileOriginal(path, *args, **kwargs)
        Path(path).unlink(missing_ok=True)
        return audio

    monkeypatch.setattr("mutagen.File", open_then_vanish)

    result = write_embedded_tags(
        str(target),
        TagWriteRequest(title="X"),
        backup_dir=backup_dir,
    )

    assert result.wrote is False
    assert result.changed is False
    assert result.backup_path is None
    assert result.error is not None
    assert not target.exists()
    assert _backup_file_count(backup_dir) == 0
    assert list(tmp_path.glob(".*.tagwrite-*")) == []
