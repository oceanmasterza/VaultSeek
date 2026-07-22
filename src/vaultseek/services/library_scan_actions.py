"""Shared helpers to run library-wide missing / quality-upgrade scans from the GUI."""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from vaultseek.core.container import Container
from vaultseek.plugins.builtin.musicbrainz import MusicBrainzProvider
from vaultseek.services.missing_media_analyzer import MissingMediaAnalyzer
from vaultseek.services.quality_upgrade_analyzer import QualityUpgradeAnalyzer


def run_missing_scan(container: Container, library_id: UUID) -> int:
    musicbrainz = next(
        (
            provider
            for provider in container.plugin_manager.get_metadata_providers()
            if isinstance(provider, MusicBrainzProvider)
        ),
        MusicBrainzProvider(),
    )
    analyzer = MissingMediaAnalyzer(
        container.album_repo,
        container.track_repo,
        musicbrainz,
        artist_repo=container.artist_repo,
    )
    prefs = container.config.acquisition
    preferred = (prefs.preferred_codec or "").strip() or None
    if prefs.prefer_lossless and not preferred:
        preferred = "FLAC"
    jobs = analyzer.create_jobs_for_library(
        container.acquisition_engine,
        library_id,
        auto_queue=prefs.auto_queue_jobs,
        preferred_codec=preferred,
    )
    logger.info("GUI missing scan created {} job(s)", len(jobs))
    return len(jobs)


def run_quality_upgrade_scan(container: Container, library_id: UUID) -> int:
    analyzer = QualityUpgradeAnalyzer(
        container.track_repo,
        album_repo=container.album_repo,
        artist_repo=container.artist_repo,
    )
    prefs = container.config.acquisition
    jobs = analyzer.create_jobs_for_library(
        container.acquisition_engine,
        library_id,
        prefs,
        auto_queue=prefs.auto_queue_jobs,
    )
    logger.info("GUI quality-upgrade scan created {} job(s)", len(jobs))
    return len(jobs)
