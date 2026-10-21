"""Тесты детектора архетипа сайта."""

from __future__ import annotations

from webscope.archetype import detect_archetype, profile_notes


def test_detects_nextjs() -> None:
    html = '<html><body><script id="__NEXT_DATA__" type="application/json">{}</script></body></html>'
    archetype = detect_archetype(html=html)
    assert archetype["framework"] == "next"


def test_detects_shopify_via_cdn() -> None:
    html = '<html><head><script src="https://cdn.shopify.com/s/x.js"></script></head></html>'
    archetype = detect_archetype(html=html)
    assert archetype["cms"] == "shopify"


def test_detects_tailwind_via_classes() -> None:
    archetype = detect_archetype(html="<html></html>", class_names=["flex", "items-center", "px-4", "text-sm"])
    assert archetype["ui_kit"] == "tailwind"


def test_detects_bootstrap_via_classes() -> None:
    archetype = detect_archetype(html="<html></html>", class_names=["btn btn-primary", "col-md-6"])
    assert archetype["ui_kit"] == "bootstrap"


def test_detects_framework_from_globals() -> None:
    archetype = detect_archetype(html="<html></html>", globals_present=["__NEXT_DATA__"])
    assert archetype["framework"] == "next"


def test_unknown_stack() -> None:
    archetype = detect_archetype(html="<html><body>hi</body></html>")
    assert archetype["framework"] is None
    assert archetype["cms"] is None


def test_profile_notes_mention_spa() -> None:
    notes = profile_notes({"framework": "next", "cms": None, "ui_kit": None})
    assert notes and "SPA" in notes[0]
