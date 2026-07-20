"""Unit tests for vaultseek.models.services.quality_scorer.

Mirrors the exact example scores from
docs/architecture/09-testing-strategy.md ("Domain Layer").
"""

from __future__ import annotations

from datetime import UTC, datetime

from vaultseek.db.uuid_utils import generate_uuid7
from vaultseek.models.entities.track import LibraryZone, Track
from vaultseek.models.services.quality_scorer import (
    DEFAULT_WEIGHTS,
    QualityScorer,
    QualityWeights,
)

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def make_track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "id": generate_uuid7(),
        "library_id": generate_uuid7(),
        "zone": LibraryZone.LIBRARY,
        "file_path": f"C:/library/{generate_uuid7()}.audio",
        "file_name": "track.audio",
        "file_size": 1024,
        "file_modified": _NOW,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


class TestQualityScorer:
    def test_flac_24bit_scores_100(self) -> None:
        track = make_track(codec="flac", is_lossless=True, bit_depth=24)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 100

    def test_flac_16bit_scores_95(self) -> None:
        track = make_track(codec="flac", is_lossless=True, bit_depth=16)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 95

    def test_lossless_with_no_bit_depth_falls_back_to_16bit_score(self) -> None:
        track = make_track(codec="flac", is_lossless=True, bit_depth=None)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 95

    def test_mp3_320_scores_70(self) -> None:
        track = make_track(codec="mp3", bitrate=320)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 70

    def test_mp3_256_scores_60(self) -> None:
        track = make_track(codec="mp3", bitrate=256)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 60

    def test_mp3_192_scores_50(self) -> None:
        track = make_track(codec="mp3", bitrate=192)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 50

    def test_mp3_128_scores_35(self) -> None:
        track = make_track(codec="mp3", bitrate=128)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 35

    def test_mp3_below_128_falls_back_to_default_lossy(self) -> None:
        track = make_track(codec="mp3", bitrate=96)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 20

    def test_aac_256_scores_65(self) -> None:
        track = make_track(codec="aac", bitrate=256)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 65

    def test_m4a_codec_name_scores_the_same_as_aac(self) -> None:
        track = make_track(codec="m4a", bitrate=256)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 65

    def test_aac_128_scores_40(self) -> None:
        track = make_track(codec="aac", bitrate=128)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 40

    def test_aac_below_128_falls_back_to_default_lossy(self) -> None:
        track = make_track(codec="aac", bitrate=64)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 20

    def test_unknown_codec_falls_back_to_default_lossy(self) -> None:
        track = make_track(codec="wma", bitrate=320)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 20

    def test_missing_codec_falls_back_to_default_lossy(self) -> None:
        track = make_track(codec=None, bitrate=320)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 20

    def test_lossy_with_no_bitrate_falls_back_to_default_lossy(self) -> None:
        track = make_track(codec="mp3", bitrate=None)
        assert QualityScorer(DEFAULT_WEIGHTS).score(track) == 20

    def test_ranks_lossless_above_lossy(self) -> None:
        flac = make_track(codec="flac", is_lossless=True, bit_depth=16)
        mp3 = make_track(codec="mp3", bitrate=320)
        ranked = QualityScorer(DEFAULT_WEIGHTS).rank([mp3, flac])
        assert ranked[0] is flac

    def test_rank_is_stable_for_equal_scores(self) -> None:
        first = make_track(codec="mp3", bitrate=320)
        second = make_track(codec="mp3", bitrate=320)
        ranked = QualityScorer(DEFAULT_WEIGHTS).rank([first, second])
        assert ranked == [first, second]

    def test_rank_of_empty_sequence_returns_empty_list(self) -> None:
        assert QualityScorer(DEFAULT_WEIGHTS).rank([]) == []

    def test_custom_weights(self) -> None:
        weights = QualityWeights(mp3_320=90)
        track = make_track(codec="mp3", bitrate=320)
        assert QualityScorer(weights).score(track) == 90
