"""Host widget that wraps toolbar controls instead of clipping them."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QSizePolicy,
    QWidget,
)

from vaultseek.gui.widgets.flow_layout import FlowLayout

_LABELED_TYPES = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QListWidget)


class FlowHost(QWidget):
    """Expanding row whose height follows the flow layout's ``heightForWidth``."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margin: int = 0,
        spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._flow = FlowLayout(self, margin=margin, spacing=spacing)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def flow(self) -> QLayout:
        return self._flow

    def uses_shared_flow_layout(self) -> bool:
        return isinstance(self._flow, FlowLayout)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt API
        return int(self._flow.heightForWidth(width))

    def add_widget(self, widget: QWidget, *, accessible_name: str | None = None) -> QWidget:
        """Add ``widget`` and keep its full label available to assistive tech."""
        apply_control_label(widget, accessible_name)
        self._flow.addWidget(widget)
        return widget


def add_labeled_field(
    host: FlowHost,
    caption: str,
    field: QWidget,
    *,
    expand: bool = False,
) -> QLabel:
    """Place a caption beside ``field`` and expose that caption as its accessible name."""
    visible = _clean_label(caption)
    label = QLabel(f"{visible}:")
    label.setBuddy(field)
    if expand:
        field.setSizePolicy(QSizePolicy.Policy.Expanding, field.sizePolicy().verticalPolicy())
    host.add_widget(label, accessible_name=visible)
    host.add_widget(field, accessible_name=visible)
    return label


def apply_control_label(widget: QWidget, accessible_name: str | None = None) -> None:
    """Record the full visible label without shortening the control text."""
    name = _clean_label(accessible_name) if accessible_name is not None else ""
    if not name:
        derived = _text_label(widget)
        if derived and not isinstance(widget, QLineEdit):
            name = derived
    if name:
        widget.setAccessibleName(name)
    tip = widget.toolTip().strip()
    if tip:
        widget.setAccessibleDescription(tip)


def ensure_control_labels(root: QWidget) -> None:
    """Fill missing accessible names from button text, placeholders, or form labels."""
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, _LABELED_TYPES):
            continue
        if not widget.accessibleName().strip():
            name = _label_for(widget)
            if name:
                widget.setAccessibleName(name)
        tip = widget.toolTip().strip()
        if tip and not widget.accessibleDescription().strip():
            widget.setAccessibleDescription(tip)


def _label_for(widget: QWidget) -> str:
    if isinstance(widget, QAbstractSpinBox):
        form_label = _form_label(widget)
        if form_label:
            return form_label
    if not isinstance(widget, QLineEdit):
        text = _text_label(widget)
        if text:
            return text
    if isinstance(widget, QLineEdit):
        placeholder = widget.placeholderText().strip()
        if placeholder:
            return placeholder
    form_label = _form_label(widget)
    if form_label:
        return form_label
    current: QWidget | None = widget.parentWidget()
    while current is not None:
        if isinstance(current, QGroupBox):
            title = _clean_label(current.title())
            if title:
                return title
        current = current.parentWidget()
    return ""


def _form_label(widget: QWidget) -> str:
    current: QWidget | None = widget
    while current is not None:
        parent = current.parentWidget()
        if parent is not None:
            layout = parent.layout()
            if isinstance(layout, QFormLayout):
                label = layout.labelForField(current)
                if isinstance(label, QLabel):
                    cleaned = _clean_label(label.text())
                    if cleaned:
                        return cleaned
        current = parent
    return ""


def _text_label(widget: QWidget) -> str:
    reader = getattr(widget, "text", None)
    if not callable(reader):
        return ""
    raw = reader()
    if not isinstance(raw, str):
        return ""
    return _clean_label(raw)


def _clean_label(text: str) -> str:
    return text.replace("&", "").strip().rstrip(":")
