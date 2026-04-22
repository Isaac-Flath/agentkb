"""Tests for the communications source registry."""

from agentkb.communications.sources import SOURCES


def test_x_registered():
    assert "x" in SOURCES


def test_fetch_and_render_are_callable():
    for src in SOURCES.values():
        assert callable(src.fetch)
        assert callable(src.render)
