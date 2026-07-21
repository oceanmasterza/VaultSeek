"""Tests for LiveLogBuffer / logging ring buffer."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from vaultseek.core.logging import LiveLogBuffer, configure_logging, get_live_log_buffer
from vaultseek.core.paths import get_app_paths


def test_live_log_buffer_rings() -> None:
    buf = LiveLogBuffer(capacity=3)
    buf.write("one\n")
    buf.write("two\n")
    buf.write("three\n")
    buf.write("four\n")
    assert buf.lines() == ("two", "three", "four")
    assert "four" in buf.text()
    assert len(buf) == 3


def test_configure_logging_attaches_live_sink(tmp_path: Path) -> None:
    paths = get_app_paths(base_override=tmp_path)
    paths.ensure_created()
    configure_logging(paths, level="INFO", console=False)
    try:
        logger.info("hello from live log test {}", 42)
        text = get_live_log_buffer().text()
        assert "hello from live log test 42" in text
    finally:
        logger.remove()
        get_live_log_buffer().clear()
