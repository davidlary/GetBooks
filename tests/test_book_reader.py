"""
Tests for book_reader.py

Uses real mirror data from openstax_mirror/ to verify:
- get_all_books() returns all expected books
- get_book() finds by title
- Section ordering (toc_order)
- Chapter section retrieval
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

MIRROR = Path(__file__).parent.parent / "openstax_mirror"


def _mirror_skip():
    if not MIRROR.exists():
        pytest.skip("openstax_mirror not present — run rsync first")


@pytest.fixture(scope="module")
def reader():
    _mirror_skip()
    from book_reader import BookReader
    return BookReader(str(MIRROR))


class TestGetAllBooks:
    def test_returns_books(self, reader):
        books = reader.get_all_books()
        assert len(books) >= 29, f"Expected >=29 books, got {len(books)}"

    def test_books_have_titles(self, reader):
        for book in reader.get_all_books():
            assert book.title, f"Book missing title: {book.metadata}"

    def test_books_have_repo_path(self, reader):
        for book in reader.get_all_books():
            assert book.repo_path.exists(), f"Repo path missing: {book.repo_path}"


class TestGetBook:
    def test_find_by_exact_title(self, reader):
        book = reader.get_book("University Physics Volume 1")
        assert book is not None
        assert book.title == "University Physics Volume 1"

    def test_find_case_insensitive(self, reader):
        book = reader.get_book("university physics volume 1")
        assert book is not None

    def test_chemistry_2e(self, reader):
        book = reader.get_book("Chemistry 2e")
        assert book is not None
        assert book.metadata.discipline == "chemistry"

    def test_not_found_returns_none(self, reader):
        book = reader.get_book("Nonexistent Book Title XYZ")
        assert book is None


class TestSectionOrdering:
    def test_sections_in_toc_order(self, reader):
        """Sections must come out in ascending toc_order."""
        book = reader.get_book("University Physics Volume 1")
        if book is None:
            pytest.skip()
        sections = book.get_sections()
        orders = [s.toc_order for s in sections]
        assert orders == sorted(orders), "Sections not in toc_order"

    def test_first_section_toc_order_positive(self, reader):
        book = reader.get_book("University Physics Volume 1")
        if book is None:
            pytest.skip()
        sections = book.get_sections()
        assert len(sections) > 0
        assert sections[0].toc_order > 0

    def test_section_numbers_present(self, reader):
        book = reader.get_book("Chemistry 2e")
        if book is None:
            pytest.skip()
        sections = book.get_sections()
        numbered = [s for s in sections if '.' in s.section_number]
        assert len(numbered) > 0, "Expected sections with X.Y numbering"


class TestChapterSections:
    def test_get_chapter_1_sections(self, reader):
        book = reader.get_book("Chemistry 2e")
        if book is None:
            pytest.skip()
        sections = book.get_chapter_sections(1)
        assert len(sections) > 0
        for s in sections:
            assert s.chapter_number == '1', f"Wrong chapter: {s.chapter_number}"

    def test_get_specific_section(self, reader):
        book = reader.get_book("Chemistry 2e")
        if book is None:
            pytest.skip()
        # Get Chapter 1, Section 1
        section = book.get_section(1, 1)
        assert section is not None
        assert section.chapter_number == '1'


class TestSeries:
    def test_university_physics_series_detected(self, reader):
        """University Physics should form a 3-volume series."""
        series = reader.get_series("University Physics")
        assert series is not None, "University Physics series not detected"
        assert len(series.volumes) == 3

    def test_series_volume_ordering(self, reader):
        series = reader.get_series("University Physics")
        if series is None:
            pytest.skip()
        titles = [v.title for v in series.volumes]
        assert "Volume 1" in titles[0]
        assert "Volume 2" in titles[1]
        assert "Volume 3" in titles[2]

    def test_book_has_series_set(self, reader):
        book = reader.get_book("University Physics Volume 1")
        if book is None:
            pytest.skip()
        assert book.series is not None
        assert book.volume_number == 1
