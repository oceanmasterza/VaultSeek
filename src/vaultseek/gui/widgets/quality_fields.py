"""Shared library-quality editors used by Settings and the setup wizard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
)

from vaultseek.core.config import AcquisitionConfig
from vaultseek.services.quality_presets import (
    PRESET_CHOICES,
    PRESET_CUSTOM,
    infer_preset,
    normalize_preset_id,
    values_for_preset,
)


class QualityFields:
    """Preset + lossless / codec / bitrate controls with infer-on-edit."""

    def __init__(self) -> None:
        self._applying = False
        self.preset = QComboBox()
        for preset_id, label, tip in PRESET_CHOICES:
            self.preset.addItem(label, preset_id)
            self.preset.setItemData(self.preset.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.preset.setToolTip(
            "Named profiles for orange traffic lights and quality upgrades. "
            "Custom keeps your manual codec / bitrate values."
        )
        self.preset_hint = QLabel("")
        self.preset_hint.setProperty("muted", True)
        self.preset_hint.setWordWrap(True)
        self.prefer_lossless = QCheckBox("Prefer lossless (FLAC/ALAC) when available")
        self.prefer_lossless.setChecked(True)
        self.preferred_codec = QLineEdit()
        self.preferred_codec.setPlaceholderText("Optional exact codec, e.g. FLAC or MP3")
        self.min_bitrate = QSpinBox()
        self.min_bitrate.setRange(0, 3200)
        self.min_bitrate.setSingleStep(32)
        self.min_bitrate.setValue(192)
        self.min_bitrate.setSuffix(" kbps")
        self.min_bitrate.setToolTip(
            "Minimum acceptable bitrate for lossy files. Green = meets this; "
            "orange = present but below. 0 disables the bitrate floor."
        )
        self.preset.currentIndexChanged.connect(self._on_preset_changed)
        self.prefer_lossless.toggled.connect(self._on_fields_edited)
        self.preferred_codec.textEdited.connect(self._on_fields_edited)
        self.min_bitrate.valueChanged.connect(self._on_fields_edited)

    def add_to_form(self, form: QFormLayout) -> None:
        """Append the standard quality rows to ``form``."""
        form.addRow("Quality preset", self.preset)
        form.addRow(self.preset_hint)
        form.addRow(self.prefer_lossless)
        form.addRow("Preferred codec", self.preferred_codec)
        form.addRow("Min bitrate (lossy)", self.min_bitrate)

    def load(self, acquisition: AcquisitionConfig) -> None:
        """Populate widgets from saved acquisition prefs."""
        self._applying = True
        key = normalize_preset_id(getattr(acquisition, "quality_preset", PRESET_CUSTOM))
        index = self.preset.findData(key)
        self.preset.setCurrentIndex(index if index >= 0 else self.preset.findData(PRESET_CUSTOM))
        self.prefer_lossless.setChecked(acquisition.prefer_lossless)
        self.preferred_codec.setText(acquisition.preferred_codec or "")
        self.min_bitrate.setValue(int(acquisition.min_bitrate_kbps))
        self._applying = False
        self._update_hint()

    def select_preset(self, preset_id: str) -> None:
        """Select a named preset and apply its values (first-run wizard)."""
        index = self.preset.findData(normalize_preset_id(preset_id))
        if index >= 0:
            self.preset.setCurrentIndex(index)

    def preset_id(self) -> str:
        return normalize_preset_id(self.preset.currentData())

    def _update_hint(self) -> None:
        tip = ""
        current = self.preset.currentData()
        for preset_id, _label, description in PRESET_CHOICES:
            if preset_id == current:
                tip = description
                break
        self.preset_hint.setText(tip)

    def _on_preset_changed(self, _index: int = 0) -> None:
        if self._applying:
            return
        values = values_for_preset(str(self.preset.currentData() or PRESET_CUSTOM))
        self._update_hint()
        if values is None:
            return
        self._applying = True
        self.prefer_lossless.setChecked(values.prefer_lossless)
        self.preferred_codec.setText(values.preferred_codec)
        self.min_bitrate.setValue(values.min_bitrate_kbps)
        self._applying = False

    def _on_fields_edited(self, *_args: object) -> None:
        if self._applying:
            return
        matched = infer_preset(
            prefer_lossless=self.prefer_lossless.isChecked(),
            preferred_codec=self.preferred_codec.text().strip(),
            min_bitrate_kbps=int(self.min_bitrate.value()),
        )
        if self.preset.currentData() != matched:
            self._applying = True
            index = self.preset.findData(matched)
            if index >= 0:
                self.preset.setCurrentIndex(index)
            self._applying = False
            self._update_hint()
