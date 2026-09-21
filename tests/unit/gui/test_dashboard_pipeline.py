"""Processing pipeline stays visible, and numeric fields stay short."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QFrame, QLabel, QWidget

from vaultseek.core.container import Container
from vaultseek.db.uuid_utils import uuid7
from vaultseek.gui.views.dashboard_page import DashboardPage
from vaultseek.gui.views.plugins_page import PluginsPage
from vaultseek.gui.views.settings_page import SettingsPage
from vaultseek.models.entities.library import Library

pytest.importorskip("pytestqt")

_SIZES = ((720, 480), (1280, 800))
_STAGE_LABELS = (
    "Discover",
    "Hash",
    "Fingerprint",
    "Identify",
    "Review",
    "Duplicates",
    "Rules",
    "Organize",
    "Artwork",
    "Acquiring",
    "Sync",
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


@pytest.fixture
def gui_library(container: Container, tmp_path: Path) -> Library:
    now = datetime.now(UTC)
    library = Library(
        id=uuid7(),
        name="Pipeline Lib",
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


def _stage_titles(page: DashboardPage) -> list[QLabel]:
    return [
        label
        for label in page._pipeline.findChildren(QLabel)  # noqa: SLF001
        if label.property("stageTitle") and label.text() in _STAGE_LABELS
    ]


def _first_row_count(flow: QWidget, titles: list[QLabel]) -> int:
    if not titles:
        return 0
    tops = [label.mapTo(flow, label.rect().topLeft()).y() for label in titles]
    top = min(tops)
    return sum(1 for y in tops if abs(y - top) <= 8)


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_pipeline_panel_visible_near_top(  # type: ignore[no-untyped-def]
    qtbot, container: Container, gui_library: Library, width: int, height: int
) -> None:
    page = DashboardPage(container)
    opened: list[str] = []
    page.navigate_requested.connect(opened.append)
    page.set_library(gui_library.id)
    _show(qtbot, page, width, height)

    panel = page.findChild(QFrame, "processingPipelinePanel")
    assert isinstance(panel, QFrame)
    assert panel.isVisible()
    assert panel.findChildren(type(page._scroll)) == []  # noqa: SLF001
    body = page._body  # noqa: SLF001
    top = panel.mapTo(body, panel.rect().topLeft()).y()
    assert top < 80, f"pipeline panel starts at y={top}, below the header"

    titles = _stage_titles(page)
    assert [label.text() for label in titles] == list(_STAGE_LABELS)
    flow = page._pipeline  # noqa: SLF001
    assert flow.height() > 60
    assert flow.width() > 200
    for label in titles:
        assert label.isVisible()
        assert label.width() > 8 and label.height() > 8
        corner = label.mapTo(flow, label.rect().bottomRight())
        assert corner.x() <= flow.width() + 2, label.text()
        assert corner.y() <= flow.height() + 2, label.text()
    assert body.width() <= page._scroll.viewport().width() + 4  # noqa: SLF001

    assert panel.isAncestorOf(page._kpi_pending)  # noqa: SLF001
    assert panel.isAncestorOf(page._kpi_running)  # noqa: SLF001
    assert panel.isAncestorOf(page._kpi_failed)  # noqa: SLF001
    assert not panel.isAncestorOf(page._kpi_acq_active)  # noqa: SLF001
    assert not panel.isAncestorOf(page._kpi_missing)  # noqa: SLF001
    pending_text = " ".join(
        label.text() for label in page._kpi_pending.findChildren(QLabel)
    )  # noqa: SLF001
    assert "0" in pending_text
    assert "Library pipeline jobs waiting" in page._kpi_pending.toolTip()  # noqa: SLF001
    wishlist = next(
        label
        for label in page.findChildren(QLabel)
        if label.text() == "Wishlist — downloads in progress"
    )
    assert (
        wishlist.mapTo(body, wishlist.rect().topLeft()).y()
        > panel.mapTo(body, panel.rect().bottomLeft()).y()
    )

    discover = next(label for label in titles if label.text() == "Discover")
    card = discover.parentWidget()
    assert isinstance(card, QFrame)
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    assert opened == ["jobs"]


def test_pipeline_wraps_more_tightly_when_narrow(  # type: ignore[no-untyped-def]
    qtbot, container: Container, gui_library: Library
) -> None:
    page = DashboardPage(container)
    page.set_library(gui_library.id)
    _show(qtbot, page, 720, 480)
    narrow_rows = _first_row_count(page._pipeline, _stage_titles(page))  # noqa: SLF001
    page.resize(1280, 800)
    _pump(page)
    qtbot.waitUntil(lambda: page.width() >= 1270, timeout=2000)
    _pump(page)
    wide_rows = _first_row_count(page._pipeline, _stage_titles(page))  # noqa: SLF001
    assert 0 < narrow_rows < len(_STAGE_LABELS)
    assert wide_rows >= narrow_rows


@pytest.mark.parametrize(("width", "height"), _SIZES)
def test_numeric_fields_stay_at_size_hint(  # type: ignore[no-untyped-def]
    qtbot, container: Container, width: int, height: int
) -> None:
    settings = SettingsPage(container)
    plugins = PluginsPage(container)
    _show(qtbot, settings, width, height)
    _show(qtbot, plugins, width, height)
    similar = plugins._lastfm_similar  # noqa: SLF001
    assert similar.accessibleName() == "Similar artists per seed"
    for page in (settings, plugins):
        boxes = [box for box in page.findChildren(QAbstractSpinBox) if box.isVisible()]
        assert boxes
        for box in boxes:
            hint = max(box.sizeHint().width(), box.minimumSizeHint().width())
            assert (
                box.width() + 4 >= hint
            ), f"{box.accessibleName()} clipped ({box.width()} < {hint})"
            assert (
                box.width() <= hint + 8
            ), f"{box.accessibleName()} stretched to {box.width()}px (hint {hint}px)"
            assert box.width() < page.width() * 0.45
