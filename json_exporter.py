"""
JSON Exporter for GetBooks

Serialises Book/Section objects to the canonical structured JSON format
consumed by SlideCreationSystem.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from book_reader import Book, BookReader, Section

logger = logging.getLogger(__name__)


def export_section(section: Section, book: Book) -> Dict[str, Any]:
    """
    Export a single Section to the canonical dict format.

    Args:
        section: Section object (content need not be pre-loaded).
        book: The Book this section belongs to.

    Returns:
        Dict matching the canonical JSON format spec.
    """
    return book.to_section_dict(section)


def export_chapter(chapter_number: int, book: Book) -> List[Dict[str, Any]]:
    """
    Export all sections of a chapter as a list of canonical dicts.

    Args:
        chapter_number: Chapter number (int).
        book: The Book.

    Returns:
        List of section dicts in toc_order.
    """
    sections = book.get_chapter_sections(chapter_number)
    return [book.to_section_dict(s) for s in sections]


def export_book(book: Book) -> List[Dict[str, Any]]:
    """
    Export all sections of a book as a list of canonical dicts.

    Args:
        book: The Book.

    Returns:
        List of all section dicts in toc_order.
    """
    return [book.to_section_dict(s) for s in book.get_sections()]


def write_json(data: Any, path: str, indent: int = 2) -> None:
    """
    Write data to a JSON file with consistent formatting.

    Args:
        data: JSON-serialisable object.
        path: Output file path.
        indent: JSON indentation (default 2).
    """
    outpath = Path(path)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    logger.info(f"Wrote JSON to {outpath} ({outpath.stat().st_size} bytes)")


def export_section_to_file(book: Book, chapter_number: int,
                            section_number, outpath: str) -> Dict[str, Any]:
    """
    Convenience: export one section directly to a file.

    Returns the exported dict.
    """
    section = book.get_section(chapter_number, section_number)
    if section is None:
        raise ValueError(
            f"Section {chapter_number}.{section_number} not found in '{book.title}'"
        )
    data = export_section(section, book)
    write_json(data, outpath)
    return data


def export_chapter_to_file(book: Book, chapter_number: int,
                            outpath: str) -> List[Dict[str, Any]]:
    """
    Convenience: export a full chapter to a file.

    Returns the list of section dicts.
    """
    data = export_chapter(chapter_number, book)
    if not data:
        raise ValueError(f"Chapter {chapter_number} not found in '{book.title}'")
    write_json(data, outpath)
    return data
