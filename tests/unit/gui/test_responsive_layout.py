"""Toolbar controls stay fully visible at the shell minimum and on a wide window."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from vaultseek.core.container import Container
from vaultseek.db.uuid_utils import uuid7
from vaultseek.gui.main_window import MainWindow
from vaultseek.gui.views.albums_page import AlbumsPage
from vaultseek.gui.views.artwork_page import ArtworkPage
from vaultseek.gui.views.library_page import LibraryPage
from vaultseek.gui.views.review_page import ReviewPage
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.gui.widgets.flow_host import FlowHost
from vaultseek.gui.widgets.flow_layout import FlowLayout
from vaultseek.models.entities.library import Library

pytest.importorskip("pytestqt")

_SIZES = ((720, 480), (1280, 800))
_CONTROL_TYPES = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QListWidget)
_EXPANDING = (
    QSizePolicy.Policy.Expanding,
    QSizePolicy.Policy.MinimumExpanding,
)


def _pump(widget: QWidget) -> None:
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.processEvents()


def _show(qtbot, widget: QWidget, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitUntil(lambda: widget.isVisible() and widget.width() >= width - 2, timeout=2000)
    _pump(widget)


def _scroll_of(widget: QWidget) -> QScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def assert_controls_contained(root: QWidget) -> None:
    """Interactive controls keep full labels and stay inside the page or its scroll viewport."""
    _pump(root)
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, _CONTROL_TYPES):
            continue
        if not widget.isVisible() or widget.width() < 2 or widget.height() < 2:
            continue
        name = widget.accessibleName().strip()
        assert name, f"{type(widget).__name__} has no accessible name"
        if isinstance(widget, QAbstractButton):
            label = widget.text().replace("&", "").strip()
            assert label, f"button {name!r} has an empty label"
            assert name == label, f"accessible name {name!r} != label {label!r}"
        policy = widget.sizePolicy().horizontalPolicy()
        if policy not in _EXPANDING and isinstance(widget, QAbstractButton):
            hint = widget.sizeHint().width()
            assert (
                widget.width() + 2 >= hint
            ), f"{name} squeezed to {widget.width()}px (needs {hint}px)"
        scroll = _scroll_of(widget)
        if scroll is not None and scroll.widget() is not None:
            content = scroll.widget()
            assert content is not None
            right = widget.mapTo(content, widget.rect().bottomRight())
            left = widget.mapTo(content, widget.rect().topLeft())
            assert left.x() >= -2, name
            assert right.x() <= content.width() + 2, f"{name} overflows the scrolled page"
            assert content.width() <= scroll.viewport().width() + 4, (
                f"{name} forces a horizontal scrollbar "
                f"({content.width()} > {scroll.viewport().width()})"
            )
            assert right.y() <= content.height() + 2, name
            continue
        right = widget.mapTo(root, widget.rect().bottomRight())
        left = widget.mapTo(root, widget.rect().topLeft())
        assert left.x() >= -2, name
        assert right.x() <= root.width() + 2, f"{name} overflows width {root.width()}"
        assert left.y() >= -2, name
        assert right.y() <= root.height() + 2, f"{name} is clipped below {root.height()}"


def test_shared_flow_layout_wraps_without_clipping(qtbot) -> None:  # type: ignore[no-untyped-def]
    holder = QWidget()
    qtbot.addWidget(holder)
    bare = FlowLayout(holder, margin=0, spacing=6)
    assert bare.spacing() == 6
    assert bare.contentsMargins().left() == 0

    host = FlowHost()
    qtbot.addWidget(host)
    labels = ("Find music…", "Archive selected…", "Delete album…", "Clear filter")
    buttons = [host.add_widget(QPushButton(label)) for label in labels]
    assert host.uses_shared_flow_layout()
    assert isinstance(host.flow(), FlowLayout)
    assert host.hasHeightForWidth()
    assert host.heightForWidth(180) > host.heightForWidth(960)
    host.resize(180, 320)
    host.show()
    qtbot.waitUntil(lambda: host.isVisible(), timeout=2000)
    _pump(host)
    for button in buttons:
        assert button.accessibleName() == button.text()
        assert button.width() + 2 >= button.sizeHint().width()
        assert button.x() + button.width() <= host.width() + 2
        assert button.y() + button.height() <= host.height() + 2


@pytest.fixture
def gui_library(container: Container, tmp_path: Path) -> Library:
    now = datetime.now(UTC)
    library = Library(
        id=uuid7(),
        name="Layout Lib",
        incoming_path=str(tmp_path / "incoming"),
        staging_path=str(tmp_path / "staging"),
        library_path=str(tmp_path / "library"),
        archive_path=str(tmp_path / "archive"),
        created_at=now,
        updated_at=now,
    )
    for path in (
        library.incoming_path,
        library.staging_path,
        library.library_path,
        library.archive_path,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
    container.library_repo.upsert(library)
    return library


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_albums_toolbar_contained(qtbot, container: Container, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    page = AlbumsPage(container)
    opened: list[str] = []
    page.navigate_requested.connect(opened.append)
    _show(qtbot, page, width, height)
    assert_controls_contained(page)
    find = next(b for b in page.findChildren(QAbstractButton) if b.text() == "Find music…")
    assert find.accessibleName() == "Find music…"
    qtbot.mouseClick(find, Qt.MouseButton.LeftButton)
    assert opened == ["find"]
    assert page._search.accessibleName() == "Search"  # noqa: SLF001


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_library_toolbar_contained(qtbot, container: Container, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    page = LibraryPage(container)
    opened: list[str] = []
    page.navigate_requested.connect(opened.append)
    _show(qtbot, page, width, height)
    assert_controls_contained(page)
    find = next(b for b in page.findChildren(QAbstractButton) if b.text() == "Find music…")
    qtbot.mouseClick(find, Qt.MouseButton.LeftButton)
    assert opened == ["find"]
    assert page._search.accessibleName() == "Search"  # noqa: SLF001
    assert page._zone.accessibleName() == "Zone"  # noqa: SLF001


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_review_actions_contained(qtbot, container: Container, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    page = ReviewPage(container)
    _show(qtbot, page, width, height)
    assert_controls_contained(page)
    labels = {b.text() for b in page.findChildren(QAbstractButton)}
    assert {"Play", "Approve", "Reject", "Defer", "Refresh"} <= labels
    assert page._approve_btn.accessibleName() == "Approve"  # noqa: SLF001
    assert page._table.isVisible() or page._empty.isVisible()  # noqa: SLF001


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_artwork_toolbar_contained(qtbot, container: Container, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    page = ArtworkPage(container)
    _show(qtbot, page, width, height)
    assert_controls_contained(page)
    assert page._search.accessibleName() == "Search"  # noqa: SLF001
    assert page._missing_only.accessibleName() == "Problems only"  # noqa: SLF001
    page._missing_only.setChecked(True)  # noqa: SLF001
    assert page._missing_only.isChecked()  # noqa: SLF001


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_settings_actions_contained(qtbot, container: Container, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    page = SettingsPage(container)
    _show(qtbot, page, width, height)
    assert page.findChild(QScrollArea) is not None
    assert_controls_contained(page)
    labels = {b.text() for b in page.findChildren(QAbstractButton)}
    assert "Save library" in labels
    assert "Save preferences" in labels
    assert "Detect local Nicotine+ and media-server settings" in labels
    assert "Move up" in labels
    delay = page._search_delay  # noqa: SLF001
    assert delay.accessibleName() == "Delay between empty sources"


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_main_shell_pages_contained(  # type: ignore[no-untyped-def]
    qtbot, container: Container, gui_library: Library, width: int, height: int
) -> None:
    del gui_library
    window = MainWindow(container)
    _show(qtbot, window, width, height)
    combo = window._library_combo  # noqa: SLF001
    assert combo.accessibleName() == "Library"
    assert combo.count() == 1
    right = combo.mapTo(window, combo.rect().bottomRight())
    assert right.x() <= window.width() + 2
    assert right.y() <= window.height() + 2
    for key in ("albums", "library", "review", "artwork", "settings"):
        window._go_to(key)  # noqa: SLF001
        _pump(window)
        page = window._pages[key]  # noqa: SLF001
        assert_controls_contained(page)
