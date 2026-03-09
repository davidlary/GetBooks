"""
Tests for series_resolver.py

Verifies series detection, volume ordering, and standalone book handling.
Uses real BookMetadata objects built from openstax_mirror/.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from cnxml_parser import BookMetadata, TOCNode
from series_resolver import (
    Series,
    detect_series,
    get_volume_number,
    is_standalone,
)


def make_book(title: str, local_path: str = "/mock") -> BookMetadata:
    """Helper: create a minimal BookMetadata for testing."""
    dummy_root = TOCNode(node_id='root', node_type='root', title='', toc_order=0)
    return BookMetadata(
        collection_id=title.lower().replace(' ', '_'),
        title=title,
        education_level='undergraduate',
        discipline='physics',
        local_path=local_path,
        collection_file=f"{local_path}/collection.xml",
        toc_root=dummy_root
    )


class TestVolumeExtraction:
    def test_volume_number_extraction(self):
        book = make_book("University Physics Volume 1")
        assert get_volume_number(book) == 1

    def test_volume_number_vol_2(self):
        book = make_book("University Physics Volume 2")
        assert get_volume_number(book) == 2

    def test_no_volume_number(self):
        book = make_book("Chemistry 2e")
        assert get_volume_number(book) is None

    def test_vol_dot_notation(self):
        book = make_book("Physics Vol. 3")
        assert get_volume_number(book) == 3

    def test_part_notation(self):
        book = make_book("Statistics Part 2")
        assert get_volume_number(book) == 2


class TestDetectSeries:
    def test_university_physics_series(self):
        """University Physics Vol 1/2/3 should form a series."""
        books = [
            make_book("University Physics Volume 1"),
            make_book("University Physics Volume 2"),
            make_book("University Physics Volume 3"),
            make_book("Chemistry 2e"),
        ]
        series_list = detect_series(books)
        up_series = [s for s in series_list if 'University Physics' in s.name]
        assert len(up_series) == 1
        assert len(up_series[0].volumes) == 3

    def test_series_volumes_in_order(self):
        """Volumes must be sorted by volume number."""
        books = [
            make_book("University Physics Volume 3"),
            make_book("University Physics Volume 1"),
            make_book("University Physics Volume 2"),
        ]
        series_list = detect_series(books)
        assert len(series_list) == 1
        titles = [v.title for v in series_list[0].volumes]
        assert titles == [
            "University Physics Volume 1",
            "University Physics Volume 2",
            "University Physics Volume 3",
        ]

    def test_standalone_book_not_in_series(self):
        """A book with no volume sibling should not appear in any series."""
        books = [
            make_book("Chemistry 2e"),
            make_book("University Physics Volume 1"),
            make_book("University Physics Volume 2"),
        ]
        series_list = detect_series(books)
        chem_series = [s for s in series_list if 'Chemistry' in s.name]
        assert len(chem_series) == 0

    def test_is_standalone_true(self):
        """Chemistry 2e is standalone among mixed books."""
        books = [
            make_book("Chemistry 2e"),
            make_book("University Physics Volume 1"),
            make_book("University Physics Volume 2"),
        ]
        chem = books[0]
        assert is_standalone(chem, books) is True

    def test_is_standalone_false(self):
        """University Physics Vol 1 is not standalone."""
        books = [
            make_book("University Physics Volume 1"),
            make_book("University Physics Volume 2"),
            make_book("University Physics Volume 3"),
        ]
        assert is_standalone(books[0], books) is False

    def test_empty_books_list(self):
        """Empty list should return no series."""
        assert detect_series([]) == []

    def test_single_book_no_series(self):
        """Single book yields no series."""
        books = [make_book("Microbiology")]
        assert detect_series(books) == []
