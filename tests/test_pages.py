"""Примечания к отчёту: что именно проверено."""

from __future__ import annotations

from webscope.pages import not_a_page_note, page_notes


def test_not_a_page_note_for_files() -> None:
    assert not_a_page_note("http://127.0.0.1:8000/README.md") is not None
    assert not_a_page_note("https://example.com/report.html") is not None
    assert not_a_page_note("https://example.com/") is None
    assert not_a_page_note("https://example.com/about") is None


def test_page_notes_include_file_warning() -> None:
    notes = page_notes("https://example.com/readme.txt", "https://example.com/readme.txt")
    assert any("файл, а не страница" in note for note in notes)
