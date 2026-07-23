"""Unit tests for named quality presets."""

from __future__ import annotations

from vaultseek.services.quality_presets import (
    PRESET_COLLECTOR,
    PRESET_COMPLETIST,
    PRESET_CUSTOM,
    PRESET_LOSSY_OK,
    infer_preset,
    normalize_preset_id,
    values_for_preset,
)


def test_named_presets_map_to_expected_values() -> None:
    completist = values_for_preset(PRESET_COMPLETIST)
    assert completist is not None
    assert completist.prefer_lossless is True
    assert completist.preferred_codec == ""
    assert completist.min_bitrate_kbps == 0

    collector = values_for_preset(PRESET_COLLECTOR)
    assert collector is not None
    assert collector.min_bitrate_kbps == 320

    lossy = values_for_preset(PRESET_LOSSY_OK)
    assert lossy is not None
    assert lossy.prefer_lossless is False
    assert lossy.preferred_codec == "MP3"
    assert lossy.min_bitrate_kbps == 192

    assert values_for_preset(PRESET_CUSTOM) is None


def test_infer_preset_round_trip() -> None:
    for preset_id in (PRESET_COMPLETIST, PRESET_COLLECTOR, PRESET_LOSSY_OK):
        values = values_for_preset(preset_id)
        assert values is not None
        assert (
            infer_preset(
                prefer_lossless=values.prefer_lossless,
                preferred_codec=values.preferred_codec,
                min_bitrate_kbps=values.min_bitrate_kbps,
            )
            == preset_id
        )
    assert (
        infer_preset(prefer_lossless=True, preferred_codec="AAC", min_bitrate_kbps=128)
        == PRESET_CUSTOM
    )


def test_normalize_preset_id() -> None:
    assert normalize_preset_id("Collector") == PRESET_COLLECTOR
    assert normalize_preset_id("nope") == PRESET_CUSTOM
    assert normalize_preset_id(None) == PRESET_CUSTOM
