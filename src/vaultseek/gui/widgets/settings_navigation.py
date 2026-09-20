"""Persistent section navigation for long configuration forms."""

from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vaultseek.gui.user_help import HelpDialog
from vaultseek.gui.widgets.flow_host import FlowHost


def add_settings_navigation(page: QWidget, scroll: QScrollArea, topic: str) -> None:
    """Keep section selection and setup help visible above the scrolling form."""
    bar = FlowHost(page, spacing=6)
    bar.flow().setContentsMargins(8, 8, 8, 4)
    sections = QComboBox()
    sections.setAccessibleName("Jump to settings section")
    sections.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
    go = QLabel("Go to")
    go.setBuddy(sections)
    bar.add_widget(go, accessible_name="Go to")
    bar.add_widget(sections, accessible_name="Jump to settings section")
    bar.add_widget(help_button)
    layout = page.layout()
    if isinstance(layout, QVBoxLayout):
        layout.insertWidget(0, bar)
