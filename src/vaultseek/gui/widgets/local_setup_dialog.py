"""Review discovered connection details before copying them into a form."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultseek.services.local_setup import LocalConnection


class LocalSetupDialog(QDialog):
    """No credential values are rendered in the discovery summary."""

    def __init__(self, connections: list[LocalConnection], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local connection suggestions")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Select the connections to copy into the form. Selected fields will replace "
            "your current entries, including any remote URL. Review, test, and Save "
            "afterward. Providers are not enabled automatically. Secrets such as "
            "qBittorrent passwords and media-server tokens are never imported from hashes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self._choices: list[tuple[QCheckBox, LocalConnection]] = []
        for connection in connections:
            status = " — listening" if connection.listening else ""
            checkbox = QCheckBox(f"{connection.name}{status}")
            checkbox.setEnabled(bool(connection.values))
            checkbox.setChecked(bool(connection.values))
            body_layout.addWidget(checkbox)
            lines = [str(connection.source), connection.note]
            summary = connection.field_summary()
            if summary:
                lines.append(summary)
            description = QLabel("\n".join(lines))
            description.setWordWrap(True)
            description.setProperty("muted", True)
            body_layout.addWidget(description)
            self._choices.append((checkbox, connection))
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        apply_button = QPushButton("Copy selected into form")
        apply_button.clicked.connect(self.accept)
        layout.addWidget(apply_button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def selected(self) -> list[LocalConnection]:
        """Return only explicitly selected, readable suggestions."""
        return [value for checkbox, value in self._choices if checkbox.isChecked()]
