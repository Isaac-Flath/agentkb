"""Tests for the communications source registry."""

from agentkb.communications.sources import SOURCES, get_all_sources, get_source


def test_x_registered():
    assert "x" in SOURCES


def test_get_all_sources():
    names = {s.name for s in get_all_sources()}
    assert "x" in names


def test_get_source():
    x = get_source("x")
    assert x.name == "x"


def test_fetch_and_render_are_callable():
    for src in get_all_sources():
        assert callable(src.fetch)
        assert callable(src.render)
