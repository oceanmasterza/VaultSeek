"""Regression tests for quality-upgrade Codex review gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine

from vaultseek.core.config import AcquisitionConfig, AppConfig, PipelineConfig
from vaultseek.core.container import Container
from vaultseek.core.event_bus import EventBus
from vaultseek.db.repositories.acquisition_job_repo import AcquisitionJobRepository
from vaultseek.db.repositories.album_repo import AlbumRepository
from vaultseek.db.repositories.artist_repo import ArtistRepository
from vaultseek.db.repositories.job_repo import JobRepository
from vaultseek.db.repositories.review_repo import ReviewRepository
from vaultseek.db.repositories.track_repo import TrackRepository
from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.acquisition_job import (
    AcquisitionJob,
    AcquisitionJobState,
    AcquisitionJobType,
)
from vaultseek.models.entities.album import Album
from vaultseek.models.entities.artist import Artist
from vaultseek.models.entities.job import JobStatus, JobType
from vaultseek.models.entities.review_item import ReviewType
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.interfaces.acquisition import SearchResult
from vaultseek.services.acquisition_engine import AcquisitionEngine
from vaultseek.services.dto.review_dto import ReviewItemCreate
from vaultseek.services.job_queue_service import JobQueueService
from vaultseek.services.quality_upgrade_analyzer import QualityUpgradeAnalyzer
from vaultseek.services.recording_identity import (
    quality_upgrade_result_compatible,
    recording_label_from_search_result,
)
from vaultseek.services.review_queue_service import ReviewQueueService
from vaultseek.services.scoring_engine import ScoringEngine
from vaultseek.services.tag_writer import TagWriteRequest, TagWriteResult

_NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _stub_tags(path: str, request: TagWriteRequest, **_kwargs: object) -> TagWriteResult:
    del request
    return TagWriteResult(path=path, wrote=True)


def _track(
    library_id: UUID,
    *,
    zone: LibraryZone = LibraryZone.LIBRARY,
    title: str = "Soul Messiah",
    path: str = "C:/library/soul.flac",
    **overrides: object,
) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": library_id,
        "zone": zone,
        "file_path": path,
        "file_name": Path(path).name,
        "file_size": 100,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
        "title": title,
        "bitrate": 192,
        "quality_score": 40.0,
        "is_lossless": False,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def _upgrade_job(**overrides: object) -> AcquisitionJob:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "job_type": AcquisitionJobType.QUALITY_UPGRADE,
        "state": AcquisitionJobState.SCORING,
        "created_at": _NOW,
        "updated_at": _NOW,
        "artist": "Alphaville",
        "album": "Salvation",
        "title": "Pandora's Lullaby",
        "preferred_codec": "flac",
    }
    defaults.update(overrides)
    return AcquisitionJob(**defaults)  # type: ignore[arg-type]


def test_better_slot_ignores_missing_corrupt_and_wrong_duration(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    reviews = ReviewRepository(engine)
    albums = AlbumRepository(engine)
    artists = ArtistRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
    )
    albums.create(album)

    good = tmp_path / "good.flac"
    good.write_bytes(b"flac")
    tracks.upsert(
        _track(
            library_id,
            path=str(good),
            album_id=album.id,
            artist_id=artist.id,
            title="Soul Messiah",
            duration_ms=240_000,
            is_lossless=True,
            quality_score=95.0,
            bitrate=1411,
        )
    )
    tracks.upsert(
        _track(
            library_id,
            path=str(tmp_path / "missing.flac"),
            album_id=album.id,
            artist_id=artist.id,
            title="Soul Messiah",
            duration_ms=240_000,
            is_lossless=True,
            quality_score=99.0,
            bitrate=1411,
        )
    )
    tracks.upsert(
        _track(
            library_id,
            path=str(tmp_path / "corrupt.flac"),
            album_id=album.id,
            artist_id=artist.id,
            title="Soul Messiah",
            duration_ms=240_000,
            is_corrupt=True,
            is_lossless=True,
            quality_score=99.0,
        )
    )
    wrong_dur = tmp_path / "wrong-dur.flac"
    wrong_dur.write_bytes(b"flac")
    tracks.upsert(
        _track(
            library_id,
            path=str(wrong_dur),
            album_id=album.id,
            artist_id=artist.id,
            title="Soul Messiah",
            duration_ms=90_000,
            is_lossless=True,
            quality_score=99.0,
        )
    )
    demo = tmp_path / "demo.flac"
    demo.write_bytes(b"flac")
    tracks.upsert(
        _track(
            library_id,
            path=str(demo),
            album_id=album.id,
            artist_id=artist.id,
            title="Soul Messiah (demo)",
            duration_ms=240_000,
            is_lossless=True,
            quality_score=99.0,
        )
    )

    incoming = tmp_path / "incoming.mp3"
    incoming.write_bytes(b"mp3")
    incoming_track = _track(
        library_id,
        zone=LibraryZone.INCOMING,
        path=str(incoming),
        album_id=album.id,
        artist_id=artist.id,
        title="Soul Messiah",
        duration_ms=241_000,
        bitrate=128,
        quality_score=20.0,
    )
    tracks.upsert(incoming_track)

    service = ReviewQueueService(
        reviews,
        tracks,
        EventBus(),
        album_repository=albums,
        artist_repository=artists,
        tag_writer=_stub_tags,
    )
    better = service._better_library_slot_copy(incoming_track)  # noqa: SLF001
    assert better is not None
    assert better.file_path == str(good)


def test_failed_retryable_upgrade_job_blocks_duplicate_scan(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    albums = AlbumRepository(engine)
    artists = ArtistRepository(engine)
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
    )
    albums.create(album)
    audio = tmp_path / "lib.mp3"
    audio.write_bytes(b"mp3")
    track = _track(
        library_id,
        path=str(audio),
        album_id=album.id,
        artist_id=artist.id,
        title="Control",
        bitrate=128,
        quality_score=10.0,
    )
    tracks.upsert(track)

    from vaultseek.services.provider_manager import ProviderManager

    acq = AcquisitionEngine(ProviderManager([]), AcquisitionJobRepository(engine))
    existing = acq.create_job(
        library_id=library_id,
        job_type=AcquisitionJobType.QUALITY_UPGRADE,
        artist="Alphaville",
        album="Salvation",
        title="Control",
    )
    acq.update_extra(existing.id, {"source_track_id": str(track.id)})
    acq.advance(existing.id, AcquisitionJobState.QUEUED)
    acq.advance(existing.id, AcquisitionJobState.SEARCHING)
    acq.advance(existing.id, AcquisitionJobState.NO_RESULTS)

    analyzer = QualityUpgradeAnalyzer(tracks, album_repo=albums, artist_repo=artists)
    prefs = AcquisitionConfig(prefer_lossless=True, preferred_codec="FLAC")
    created = analyzer.create_jobs_for_library(acq, library_id, prefs)
    assert created == []
    again = analyzer.create_job_for_track(acq, track.id, prefs)
    assert again is None


def test_wrong_studio_title_rejected_even_with_sibling_track_count() -> None:
    wrong = SearchResult(
        result_id="wrong",
        provider_id="nicotine_plus",
        display_name="Alphaville - Soul Messiah.flac",
        title="Soul Messiah",
        artist="Alphaville",
        album="Salvation",
        format="flac",
        track_count=1,
    )
    demo_with_siblings = SearchResult(
        result_id="demo",
        provider_id="nicotine_plus",
        display_name="12 - Pandora's Lullaby (Demo).flac",
        title="Pandora's Lullaby (Demo)",
        artist="Alphaville",
        album="Salvation",
        format="flac",
        track_count=12,
        raw={"file_path": "Alphaville/Salvation/12 - Pandora's Lullaby (Demo).flac"},
    )
    assert quality_upgrade_result_compatible("Pandora's Lullaby", wrong) is False
    assert quality_upgrade_result_compatible("Pandora's Lullaby", demo_with_siblings) is False
    job = _upgrade_job(title="Pandora's Lullaby")
    scored = ScoringEngine().score_results(job, [wrong, demo_with_siblings])
    assert scored == []


def test_named_mixes_conflict_and_band_live_is_valid() -> None:
    radio = SearchResult(
        result_id="radio",
        provider_id="nicotine_plus",
        display_name="Song (Radio Mix).flac",
        title="Song (Radio Mix)",
        format="flac",
    )
    club = SearchResult(
        result_id="club",
        provider_id="nicotine_plus",
        display_name="Song (Club Mix).flac",
        title="Song (Club Mix)",
        format="flac",
    )
    assert quality_upgrade_result_compatible("Song (Radio Mix)", club) is False
    assert quality_upgrade_result_compatible("Song (Radio Mix)", radio) is True

    live_band = SearchResult(
        result_id="live-band",
        provider_id="nicotine_plus",
        display_name="Live - All Over You.flac",
        title="All Over You",
        artist="Live",
        album="Throwing Copper",
        format="flac",
        raw={"file_path": "Live/Throwing Copper/05 - All Over You.flac"},
    )
    assert recording_label_from_search_result(live_band) == "All Over You"
    assert quality_upgrade_result_compatible("All Over You", live_band) is True
    job = _upgrade_job(artist="Live", album="Throwing Copper", title="All Over You")
    assert ScoringEngine().score_one(job, live_band) > 0.0


def test_legitimate_album_pack_allowed_for_quality_upgrade() -> None:
    pack = SearchResult(
        result_id="pack",
        provider_id="prowlarr_public",
        display_name="Alphaville - Salvation (1999) FLAC",
        title=None,
        artist="Alphaville",
        album="Salvation",
        format="flac",
        track_count=12,
    )
    nzb = SearchResult(
        result_id="nzb",
        provider_id="usenet",
        display_name="Alphaville-Salvation-FLAC-1999",
        title=None,
        artist="Alphaville",
        album="Salvation",
        format="flac",
        track_count=12,
        raw={"file_path": "Alphaville-Salvation-FLAC-1999.nzb"},
    )
    assert quality_upgrade_result_compatible("Pandora's Lullaby", pack) is True
    assert quality_upgrade_result_compatible("Pandora's Lullaby", nzb) is True
    job = _upgrade_job()
    assert ScoringEngine().score_one(job, pack) > 0.0
    assert ScoringEngine().score_one(job, nzb) > 0.0


def test_scoped_quality_upgrade_uses_replaced_container_config(tmp_path: Path) -> None:
    """Settings/Plugins replace container.config; callback must not keep bootstrap prefs."""
    from vaultseek.core.paths import get_app_paths
    from vaultseek.services.quality_upgrade_analyzer import QualityUpgradeAnalyzer

    paths = get_app_paths(base_override=tmp_path)
    paths.ensure_created()
    container = Container.bootstrap(
        paths=paths,
        config=AppConfig(
            acquisition=AcquisitionConfig(prefer_lossless=False, preferred_codec="MP3")
        ),
    )
    try:
        container.acquisition_automation_service.stop()
        container.watch_folder.stop()
        container.dispatcher.stop()

        captured: list[AcquisitionConfig] = []
        upgrader = container.organizer_worker._quality_upgrader  # noqa: SLF001
        assert upgrader is not None
        assert upgrader.__closure__ is not None
        analyzer = next(
            cell.cell_contents
            for cell in upgrader.__closure__
            if isinstance(cell.cell_contents, QualityUpgradeAnalyzer)
        )

        def _fake_create(
            acquisition_engine: object,
            track_id: UUID,
            prefs: AcquisitionConfig,
            *,
            auto_queue: bool = False,
        ) -> None:
            del acquisition_engine, track_id, auto_queue
            captured.append(prefs)

        analyzer.create_job_for_track = _fake_create  # type: ignore[method-assign]

        container.config = replace(
            container.config,
            acquisition=replace(
                container.config.acquisition,
                preferred_codec="FLAC",
                prefer_lossless=True,
                auto_queue_jobs=True,
            ),
        )
        upgrader(generate_uuid7())
        assert captured
        assert captured[0].preferred_codec == "FLAC"
        assert captured[0].prefer_lossless is True
        assert captured[0].auto_queue_jobs is True
    finally:
        container.close()


def test_library_assign_enqueues_same_zone_reorganize(
    engine: Engine, library_id: UUID, tmp_path: Path
) -> None:
    tracks = TrackRepository(engine)
    reviews = ReviewRepository(engine)
    albums = AlbumRepository(engine)
    artists = ArtistRepository(engine)
    jobs = JobRepository(engine)
    queue = JobQueueService(jobs, PipelineConfig())
    artist = Artist(
        id=generate_uuid7(),
        name="Alphaville",
        sort_name="Alphaville",
        created_at=_NOW,
        updated_at=_NOW,
    )
    artists.create(artist)
    old_album = Album(
        id=generate_uuid7(),
        title="Forever Pop",
        sort_title="Forever Pop",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
    )
    new_album = Album(
        id=generate_uuid7(),
        title="Salvation",
        sort_title="Salvation",
        created_at=_NOW,
        updated_at=_NOW,
        album_artist_id=artist.id,
    )
    albums.create(old_album)
    albums.create(new_album)
    seed = tmp_path / "seed.flac"
    seed.write_bytes(b"flac")
    tracks.upsert(
        _track(
            library_id,
            path=str(seed),
            album_id=new_album.id,
            artist_id=artist.id,
            title="Control",
            track_number=7,
        )
    )
    audio = tmp_path / "10 - Soul Messiah.mp3"
    audio.write_bytes(b"mp3")
    track = _track(
        library_id,
        path=str(audio),
        album_id=old_album.id,
        artist_id=artist.id,
        title="Soul Messiah",
        track_number=10,
    )
    tracks.upsert(track)
    tracks.upsert(
        _track(
            library_id,
            path=str(tmp_path / "other.flac"),
            album_id=old_album.id,
            artist_id=artist.id,
            title="Other",
        )
    )
    service = ReviewQueueService(
        reviews,
        tracks,
        EventBus(),
        job_queue=queue,
        album_repository=albums,
        artist_repository=artists,
        tag_writer=_stub_tags,
    )
    item_id = service.create_item(
        ReviewItemCreate(
            library_id=library_id,
            review_type=ReviewType.UNKNOWN_ALBUM,
            title="reassign",
            track_id=track.id,
            description="test",
            confidence=0.5,
        )
    )
    service.assign_album_slot(
        item_id,
        album_id=new_album.id,
        title="Soul Messiah",
        track_number=10,
        disc_number=1,
        artist_id=artist.id,
        now=_NOW,
    )
    organize = [
        job
        for job in jobs.list_by_status(JobStatus.PENDING)
        if job.job_type is JobType.ORGANIZE_FILE
    ]
    assert any(
        job.payload.get("reorganize") is True
        and job.payload.get("target_zone") == LibraryZone.LIBRARY.value
        for job in organize
    )


def test_radio_and_single_edit_conflict_with_bare_studio() -> None:
    from vaultseek.services.recording_identity import recordings_compatible

    assert recordings_compatible("Pandora's Lullaby", "Pandora's Lullaby (Radio Mix)") is False
    assert recordings_compatible("Pandora's Lullaby", "Pandora's Lullaby (Single Edit)") is False
    assert (
        recordings_compatible("Pandora's Lullaby (Radio Mix)", "Pandora's Lullaby (Radio Mix)")
        is True
    )
    assert recordings_compatible("Pandora's Lullaby", "Pandora's Lullaby") is True
