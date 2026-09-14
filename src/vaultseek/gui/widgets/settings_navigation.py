"""Persistent section navigation for long configuration forms."""

from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultseek.gui.user_help import HelpDialog


def add_settings_navigation(page: QWidget, scroll: QScrollArea, topic: str) -> None:
    """Keep section selection and setup help visible above the scrolling form."""
    bar = QWidget(page)
    row = QHBoxLayout(bar)
    sections = QComboBox()
    sections.setAccessibleName("Jump to settings section")
    sections.addItem("Jump to a section…", None)
    body = scroll.widget()
    assert body is not None
    for box in body.findChildren(QGroupBox):
        sections.addItem(box.title(), box)
    sections.currentIndexChanged.connect(
        lambda _: (
            scroll.ensureWidgetVisible(sections.currentData(), 0, 20)
            if sections.currentData() is not None
            else None
        )
    )
    help_button = QPushButton("Setup instructions")
    help_button.clicked.connect(lambda: HelpDialog(page, topic=topic).exec())
    row.addWidget(QLabel("Go to"))
    row.addWidget(sections, 1)
    row.addWidget(help_button)
    layout = page.layout()
    if isinstance(layout, QVBoxLayout):
        layout.insertWidget(0, bar)
