"""Review discovered connection details before copying them into a form."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultseek.services.local_setup import LocalConnection


class LocalSetupDialog(QDialog):
    """No credential values are rendered in the discovery summary."""

    def __init__(self, connections: list[LocalConnection], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local connection suggestions")
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Select the connections to copy into the form. Selected fields will replace "
            "your current entries, including any remote URL. Review, test, and Save "
            "afterward. Providers are not enabled automatically. Secrets such as "
            "qBittorrent passwords and media-server tokens are never imported from hashes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._choices: list[tuple[QCheckBox, LocalConnection]] = []
        for connection in connections:
            status = " — listening" if connection.listening else ""
            checkbox = QCheckBox(f"{connection.name}{status}")
            checkbox.setEnabled(bool(connection.values))
            checkbox.setChecked(bool(connection.values))
            layout.addWidget(checkbox)
            description = QLabel(f"{connection.source}\n{connection.note}")
            description.setWordWrap(True)
            layout.addWidget(description)
            self._choices.append((checkbox, connection))
        apply_button = QPushButton("Copy selected into form")
        apply_button.clicked.connect(self.accept)
        layout.addWidget(apply_button)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def selected(self) -> list[LocalConnection]:
        """Return only explicitly selected, readable suggestions."""
        return [value for checkbox, value in self._choices if checkbox.isChecked()]
