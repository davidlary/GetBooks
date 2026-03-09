"""
Tests for json_exporter.py

Round-trip test: export section → reload → assert fields correct.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

MIRROR = Path(__file__).parent.parent / "openstax_mirror"

REQUIRED_TOP_FIELDS = {'book', 'subject', 'level', 'chapter', 'section',
                        'learning_objectives', 'content'}
REQUIRED_CHAPTER_FIELDS = {'number', 'title'}
REQUIRED_SECTION_FIELDS = {'number', 'title', 'toc_order'}


def _mirror_skip():
    if not MIRROR.exists():
        pytest.skip("openstax_mirror not present")


@pytest.fixture(scope="module")
def chem_chapter1(tmp_path_factory):
    """Export Chemistry 2e Chapter 1 to a temp file and return the data."""
    _mirror_skip()
    from book_reader import BookReader
    from json_exporter import export_chapter_to_file

    reader = BookReader(str(MIRROR))
    book = reader.get_book("Chemistry 2e")
    if book is None:
        pytest.skip("Chemistry 2e not found in mirror")

    tmp = tmp_path_factory.mktemp("exports")
    outpath = str(tmp / "chem_ch1.json")
    data = export_chapter_to_file(book, 1, outpath)
    return data, outpath


class TestExportFormat:
    def test_returns_list(self, chem_chapter1):
        data, _ = chem_chapter1
        assert isinstance(data, list), "Chapter export should be a list"

    def test_sections_non_empty(self, chem_chapter1):
        data, _ = chem_chapter1
        assert len(data) > 0, "Chapter should have at least one section"

    def test_required_fields_present(self, chem_chapter1):
        data, _ = chem_chapter1
        for section in data:
            for field in REQUIRED_TOP_FIELDS:
                assert field in section, f"Missing field: {field}"

    def test_chapter_fields(self, chem_chapter1):
        data, _ = chem_chapter1
        for section in data:
            ch = section['chapter']
            for f in REQUIRED_CHAPTER_FIELDS:
                assert f in ch, f"chapter missing field: {f}"

    def test_section_fields(self, chem_chapter1):
        data, _ = chem_chapter1
        for section in data:
            sec = section['section']
            for f in REQUIRED_SECTION_FIELDS:
                assert f in sec, f"section missing field: {f}"

    def test_content_is_list(self, chem_chapter1):
        data, _ = chem_chapter1
        for section in data:
            assert isinstance(section['content'], list)

    def test_content_blocks_have_type(self, chem_chapter1):
        data, _ = chem_chapter1
        for section in data:
            for block in section['content']:
                assert 'type' in block, f"Content block missing 'type': {block}"


class TestRoundTrip:
    def test_file_is_valid_json(self, chem_chapter1):
        _, outpath = chem_chapter1
        with open(outpath, 'r') as f:
            reloaded = json.load(f)
        assert isinstance(reloaded, list)
        assert len(reloaded) > 0

    def test_roundtrip_preserves_book_title(self, chem_chapter1):
        data, outpath = chem_chapter1
        with open(outpath, 'r') as f:
            reloaded = json.load(f)
        for orig, reloaded_sec in zip(data, reloaded):
            assert orig['book'] == reloaded_sec['book']

    def test_roundtrip_preserves_chapter_number(self, chem_chapter1):
        data, outpath = chem_chapter1
        with open(outpath, 'r') as f:
            reloaded = json.load(f)
        for orig, rel in zip(data, reloaded):
            assert orig['chapter']['number'] == rel['chapter']['number']


class TestSectionExport:
    def test_export_single_section(self):
        _mirror_skip()
        from book_reader import BookReader
        from json_exporter import export_section_to_file

        reader = BookReader(str(MIRROR))
        book = reader.get_book("Chemistry 2e")
        if book is None:
            pytest.skip()

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            outpath = f.name

        data = export_section_to_file(book, 1, 1, outpath)
        assert isinstance(data, dict)
        assert 'book' in data
        assert 'content' in data
        assert data['chapter']['number'] == 1
