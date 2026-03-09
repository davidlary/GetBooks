"""
BookReader - Public API for GetBooks

Provides a clean interface to read books, chapters, and sections from
the OpenStax CNXML mirror.

Usage:
    reader = BookReader("openstax_mirror/")
    books = reader.get_all_books()
    book = reader.get_book("University Physics Volume 1")
    for section in book.iter_sections():
        data = section.to_dict()
    reader.export_section_json("University Physics Volume 1", 4, 2, "sec_4_2.json")
    reader.export_chapter_json("University Physics Volume 1", 4, "ch_4.json")
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, List, Optional

from cnxml_parser import (
    BookMetadata,
    SectionContent,
    TOCNode,
    find_collection_files,
    parse_collection_xml,
    extract_section_content,
)
from series_resolver import Series, detect_series

logger = logging.getLogger(__name__)


@dataclass
class Section:
    """A book section with its full content, ready for export."""
    book_metadata: BookMetadata
    toc_node: TOCNode           # The section's TOC node
    chapter_node: TOCNode       # Parent chapter node
    unit_node: Optional[TOCNode] = None  # Parent unit (hierarchical books only)
    content: Optional[SectionContent] = None  # Loaded on demand

    @property
    def module_id(self) -> str:
        return self.toc_node.module_id or ''

    @property
    def section_number(self) -> str:
        return self.toc_node.number

    @property
    def section_title(self) -> str:
        return self.toc_node.title

    @property
    def chapter_number(self) -> str:
        return self.chapter_node.number

    @property
    def chapter_title(self) -> str:
        return self.chapter_node.title

    @property
    def toc_order(self) -> int:
        return self.toc_node.toc_order

    def load_content(self, repo_path: Path) -> SectionContent:
        """Load and cache section content from the CNXML module file."""
        if self.content is not None:
            return self.content
        module_path = repo_path / 'modules' / self.module_id / 'index.cnxml'
        if not module_path.exists():
            logger.warning(f"Module file not found: {module_path}")
            return None
        try:
            self.content = extract_section_content(module_path, repo_path)
            self.content.section_number = self.section_number
            self.content.toc_order = self.toc_order
            # If the TOC node has a placeholder title, use the actual module title
            if (self.content.title and self.content.title != 'Untitled' and
                    (not self.toc_node.title or
                     self.toc_node.title.startswith('Section '))):
                self.toc_node.title = self.content.title
        except Exception as e:
            logger.error(f"Error loading {module_path}: {e}")
            return None
        return self.content

    def to_dict(self, repo_path: Path = None) -> dict:
        """
        Export this section as the canonical JSON dict format.

        Matches the spec:
          book, series, volume, subject, level, chapter, section,
          learning_objectives, content[]
        """
        bm = self.book_metadata
        # Load content if not already loaded
        if self.content is None and repo_path is not None:
            self.load_content(repo_path)

        content_blocks = []
        learning_objectives = []
        if self.content:
            learning_objectives = self.content.learning_objectives
            for block in self.content.content_blocks:
                block_dict = {'type': block.block_type}
                if block.block_type == 'paragraph':
                    block_dict['text'] = block.text or ''
                elif block.block_type == 'equation':
                    block_dict['mathml'] = block.mathml or ''
                    block_dict['latex'] = block.latex or ''
                elif block.block_type == 'figure':
                    block_dict['image_path'] = block.image_path or ''
                    block_dict['caption'] = block.caption or ''
                elif block.block_type == 'table':
                    block_dict['title'] = block.title or ''
                    block_dict['headers'] = block.headers
                    block_dict['rows'] = block.rows
                elif block.block_type == 'example':
                    block_dict['title'] = block.title or ''
                    block_dict['problem'] = block.problem or ''
                    block_dict['solution'] = block.solution or ''
                elif block.block_type == 'exercise':
                    block_dict['problem'] = block.problem or ''
                    block_dict['solution'] = block.solution or ''
                elif block.block_type == 'note':
                    block_dict['note_type'] = block.note_type or 'note'
                    block_dict['title'] = block.title or ''
                    block_dict['text'] = block.text or ''
                elif block.block_type == 'list':
                    block_dict['list_type'] = block.list_type or 'bullet'
                    block_dict['items'] = block.items
                elif block.block_type == 'definition':
                    block_dict['term'] = block.term or ''
                    block_dict['meaning'] = block.meaning or ''
                elif block.block_type == 'subsection':
                    block_dict['title'] = block.title or ''
                    block_dict['level'] = block.level
                content_blocks.append(block_dict)

        return {
            'book': bm.title,
            'series': None,     # Filled by Book.to_section_dict() if applicable
            'volume': None,     # Filled by Book if series
            'subject': bm.discipline,
            'level': bm.education_level,
            'chapter': {
                'number': int(self.chapter_number) if self.chapter_number.isdigit() else self.chapter_number,
                'title': self.chapter_title
            },
            'section': {
                'number': self.section_number,
                'title': self.section_title,
                'toc_order': self.toc_order
            },
            'learning_objectives': learning_objectives,
            'content': content_blocks
        }


@dataclass
class Book:
    """A single OpenStax book (corresponds to one collection.xml)."""
    metadata: BookMetadata
    repo_path: Path
    series: Optional[Series] = None
    volume_number: Optional[int] = None
    _sections: Optional[List[Section]] = field(default=None, repr=False)

    @property
    def title(self) -> str:
        return self.metadata.title

    def _build_sections(self) -> List[Section]:
        """Build the flat list of sections in toc_order from the TOC tree."""
        sections = []
        toc_root = self.metadata.toc_root
        if toc_root is None:
            return sections

        def walk_unit(unit_node: TOCNode, chapter_nodes):
            for ch in chapter_nodes:
                for sec in ch.children:
                    if sec.node_type == 'section':
                        sections.append(Section(
                            book_metadata=self.metadata,
                            toc_node=sec,
                            chapter_node=ch,
                            unit_node=unit_node if unit_node.node_type == 'unit' else None
                        ))

        for child in toc_root.children:
            if child.node_type == 'unit':
                walk_unit(child, child.children)
            elif child.node_type == 'chapter':
                for sec in child.children:
                    if sec.node_type == 'section':
                        sections.append(Section(
                            book_metadata=self.metadata,
                            toc_node=sec,
                            chapter_node=child
                        ))
            elif child.node_type == 'section':
                # Flat TOC — create dummy chapter
                dummy_ch = TOCNode(node_id='ch_0', node_type='chapter',
                                   title='', number='0', toc_order=0)
                sections.append(Section(
                    book_metadata=self.metadata,
                    toc_node=child,
                    chapter_node=dummy_ch
                ))

        return sorted(sections, key=lambda s: s.toc_order)

    def get_sections(self) -> List[Section]:
        """Return all sections sorted by toc_order (cached)."""
        if self._sections is None:
            self._sections = self._build_sections()
        return self._sections

    def iter_sections(self) -> Generator[Section, None, None]:
        """Yield all sections in toc_order with content loaded."""
        for section in self.get_sections():
            section.load_content(self.repo_path)
            yield section

    def get_chapter_sections(self, chapter_number: int) -> List[Section]:
        """Return all sections in a specific chapter (by number)."""
        result = []
        for section in self.get_sections():
            try:
                if int(section.chapter_number) == chapter_number:
                    result.append(section)
            except (ValueError, TypeError):
                if section.chapter_number == str(chapter_number):
                    result.append(section)
        return result

    def get_section(self, chapter_number: int, section_number) -> Optional[Section]:
        """Return a specific section by chapter and section number."""
        sec_str = str(section_number)
        for section in self.get_sections():
            if (section.chapter_number == str(chapter_number) and
                    (section.section_number == sec_str or
                     section.section_number.endswith(f'.{sec_str}'))):
                return section
        return None

    def to_section_dict(self, section: Section) -> dict:
        """Export a section as dict with series/volume info filled in."""
        section.load_content(self.repo_path)
        d = section.to_dict(self.repo_path)
        if self.series:
            d['series'] = self.series.name
            d['volume'] = self.volume_number
        return d


class BookReader:
    """
    Public API for reading OpenStax books from the local mirror.

    Args:
        mirror_dir: Path to the openstax_mirror/ directory.
    """

    def __init__(self, mirror_dir: str = "openstax_mirror"):
        self.mirror_path = Path(mirror_dir)
        if not self.mirror_path.exists():
            raise FileNotFoundError(f"Mirror directory not found: {mirror_dir}")
        self._books: Optional[List[Book]] = None
        self._series_list: Optional[List[Series]] = None

    def _load_all(self):
        """Parse all collection.xml files in the mirror."""
        if self._books is not None:
            return

        all_metadata: List[BookMetadata] = []
        repo_map: Dict[str, Path] = {}  # collection_id -> repo_path

        for repo_dir in sorted(self.mirror_path.iterdir()):
            if not repo_dir.is_dir():
                continue
            if repo_dir.name.startswith('.') or repo_dir.name in ('inventory.json', 'inventory.md'):
                continue

            collection_files = find_collection_files(repo_dir)
            for col_file in collection_files:
                try:
                    bm = parse_collection_xml(col_file)
                    all_metadata.append(bm)
                    repo_map[bm.collection_id] = repo_dir
                    logger.info(f"Loaded: {bm.title}")
                except Exception as e:
                    logger.warning(f"Skipping {col_file}: {e}")

        # Detect series
        self._series_list = detect_series(all_metadata)

        # Build lookup: collection_id -> (series, volume_number)
        series_lookup: Dict[str, tuple] = {}
        for series in self._series_list:
            for vol_idx, vol in enumerate(series.volumes, 1):
                # Use volume number from title if present
                from series_resolver import get_volume_number
                vol_num = get_volume_number(vol) or vol_idx
                series_lookup[vol.collection_id] = (series, vol_num)

        self._books = []
        for bm in all_metadata:
            repo_path = repo_map[bm.collection_id]
            ser, vol_num = series_lookup.get(bm.collection_id, (None, None))
            self._books.append(Book(
                metadata=bm,
                repo_path=repo_path,
                series=ser,
                volume_number=vol_num
            ))

    def get_all_books(self) -> List[Book]:
        """Return all books found in the mirror."""
        self._load_all()
        return sorted(self._books, key=lambda b: b.title)

    def get_book(self, title: str) -> Optional[Book]:
        """Return a Book by exact or case-insensitive title match."""
        self._load_all()
        title_lower = title.lower().strip()
        for book in self._books:
            if book.title.lower().strip() == title_lower:
                return book
        return None

    def get_series(self, name: str) -> Optional[Series]:
        """Return a Series by name (case-insensitive)."""
        self._load_all()
        name_lower = name.lower().strip()
        for series in self._series_list:
            if series.name.lower().strip() == name_lower:
                return series
        return None

    def get_all_series(self) -> List[Series]:
        """Return all detected series."""
        self._load_all()
        return sorted(self._series_list, key=lambda s: s.name)

    def export_section_json(self, book_title: str, chapter_number: int,
                             section_number, outpath: str) -> dict:
        """
        Export a single section to a JSON file.

        Args:
            book_title: Exact book title.
            chapter_number: Chapter number (int).
            section_number: Section number within chapter (int or "4.2"-style string).
            outpath: Output file path.

        Returns:
            The exported dict.
        """
        book = self.get_book(book_title)
        if book is None:
            raise ValueError(f"Book not found: {book_title!r}")
        section = book.get_section(chapter_number, section_number)
        if section is None:
            raise ValueError(f"Section not found: chapter {chapter_number}, section {section_number}")
        data = book.to_section_dict(section)
        with open(outpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported section JSON to {outpath}")
        return data

    def export_chapter_json(self, book_title: str, chapter_number: int,
                             outpath: str) -> list:
        """
        Export all sections of a chapter to a JSON array file.

        Returns:
            List of section dicts.
        """
        book = self.get_book(book_title)
        if book is None:
            raise ValueError(f"Book not found: {book_title!r}")
        sections = book.get_chapter_sections(chapter_number)
        if not sections:
            raise ValueError(f"Chapter {chapter_number} not found in {book_title!r}")
        data = [book.to_section_dict(s) for s in sections]
        with open(outpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported chapter JSON ({len(data)} sections) to {outpath}")
        return data
