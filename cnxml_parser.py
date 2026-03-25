"""
CNXML Parser for GetBooks

Parses OpenStax CNXML (Connexions XML) files into structured Python dataclasses.
Handles all 3 TOC patterns and extracts all content element types needed for slides.

Three TOC patterns:
1. Hierarchical: Unit -> Chapter -> Section (University Physics vols)
2. Chapter-only: Chapter -> Section (Chemistry, Biology, most books)
3. Flat: Direct modules (rare)

Bundle detection: finds all *.collection.xml in collections/ directory.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from lxml import etree

logger = logging.getLogger(__name__)

# CNXML Namespaces
NAMESPACES = {
    'col': 'http://cnx.rice.edu/collxml',
    'cnxml': 'http://cnx.rice.edu/cnxml',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'md': 'http://cnx.rice.edu/mdml',
    'm': 'http://www.w3.org/1998/Math/MathML'
}

DISCIPLINE_PATTERNS = {
    'physics': ['physics'],
    'chemistry': ['chemistry'],
    'biology': ['biology', 'microbiology'],
    'mathematics': ['calculus', 'algebra', 'prealgebra', 'contemporary-mathematics', 'statistics'],
    'anatomy': ['anatomy'],
    'astronomy': ['astronomy'],
    'economics': ['economics'],
    'psychology': ['psychology'],
    'sociology': ['sociology'],
    'business': ['business', 'entrepreneurship'],
    'accounting': ['accounting'],
    'history': ['history'],
    'government': ['government'],
    'political_science': ['political-science'],
    'philosophy': ['philosophy'],
    'anthropology': ['anthropology'],
    'intellectual_property': ['intellectual-property'],
    'college_success': ['college-success']
}


def identify_discipline(path: str) -> str:
    """Identify OpenStax discipline from textbook directory name."""
    path_lower = str(path).lower()
    for discipline, patterns in DISCIPLINE_PATTERNS.items():
        if any(p in path_lower for p in patterns):
            return discipline
    return 'unknown'


@dataclass
class TOCNode:
    """Node in Table of Contents hierarchy."""
    node_id: str
    node_type: str  # root, unit, chapter, section
    title: str
    number: str = ""
    toc_order: int = 0
    module_id: Optional[str] = None
    children: List['TOCNode'] = field(default_factory=list)


@dataclass
class ContentBlock:
    """Single extracted content block from a CNXML module."""
    block_id: str
    block_type: str
    # Common fields
    text: Optional[str] = None
    # Equation fields
    mathml: Optional[str] = None
    latex: Optional[str] = None
    # Figure fields
    image_path: Optional[str] = None
    caption: Optional[str] = None
    # Table fields
    title: Optional[str] = None
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    # Example/exercise fields
    problem: Optional[str] = None
    solution: Optional[str] = None
    # Note fields
    note_type: Optional[str] = None
    # Definition fields
    term: Optional[str] = None
    meaning: Optional[str] = None
    # List fields
    list_type: Optional[str] = None   # bullet or numbered
    items: List[str] = field(default_factory=list)
    # Subsection
    level: int = 0


@dataclass
class SectionContent:
    """Complete content for a single section/module."""
    module_id: str
    title: str
    section_number: str = ""
    toc_order: int = 0
    learning_objectives: List[str] = field(default_factory=list)
    content_blocks: List[ContentBlock] = field(default_factory=list)
    term_tags: List[str] = field(default_factory=list)


@dataclass
class BookMetadata:
    """Metadata for a single book (one collection.xml)."""
    collection_id: str
    title: str
    education_level: str
    discipline: str
    local_path: str       # repo root dir
    collection_file: str  # path to *.collection.xml
    toc_fingerprint: str = ""
    unit_count: int = 0
    chapter_count: int = 0
    section_count: int = 0
    toc_root: Optional[TOCNode] = None


def find_collection_files(repo_path: Path) -> List[Path]:
    """
    Find all collection XML files in a repo.
    Checks collections/ dir for *.collection.xml, falls back to legacy collection.cnxml.
    Returns list of Paths (one per book; bundles have multiple).
    """
    files = []
    collections_dir = repo_path / 'collections'
    if collections_dir.exists():
        for p in sorted(collections_dir.glob('*.collection.xml')):
            files.append(p)
    # Legacy fallback
    if not files:
        for p in repo_path.rglob('collection.cnxml'):
            files.append(p)
    return files


def parse_collection_xml(path: Path) -> BookMetadata:
    """
    Parse a *.collection.xml file into BookMetadata with full TOC hierarchy.
    """
    if not path.exists():
        raise FileNotFoundError(f"Collection file not found: {path}")

    tree = etree.parse(str(path))
    root = tree.getroot()

    # Title
    title_elem = root.find('.//md:title', NAMESPACES)
    if title_elem is None or not title_elem.text:
        raise ValueError(f"Collection missing title: {path}")
    title = title_elem.text.strip()

    # UUID
    uuid_elem = root.find('.//md:uuid', NAMESPACES)
    collection_id = uuid_elem.text.strip() if uuid_elem is not None and uuid_elem.text else ""

    # Education level
    level_elem = root.find('.//md:educationlevel', NAMESPACES)
    level = level_elem.text.strip() if level_elem is not None and level_elem.text else ""
    if not level:
        tl = title.lower()
        if any(k in tl for k in ['ap ', 'advanced placement', 'high school']):
            level = 'high school'
        else:
            level = 'undergraduate'

    # Repo root: go up from collections/book.collection.xml to repo root
    if 'collections' in str(path.parent):
        repo_root = path.parent.parent
    else:
        repo_root = path.parent.parent  # Legacy: modules/collection.cnxml -> repo root

    discipline = identify_discipline(str(repo_root))

    # Extract TOC
    toc_root, _ = extract_toc_hierarchy(root, collection_id)

    # Count nodes
    unit_count = chapter_count = section_count = 0
    for child in toc_root.children:
        if child.node_type == 'unit':
            unit_count += 1
            for ch in child.children:
                chapter_count += 1
                section_count += len(ch.children)
        elif child.node_type == 'chapter':
            chapter_count += 1
            section_count += len(child.children)
        elif child.node_type == 'section':
            section_count += 1

    fingerprint = _toc_fingerprint(toc_root)

    return BookMetadata(
        collection_id=collection_id,
        title=title,
        education_level=level,
        discipline=discipline,
        local_path=str(repo_root),
        collection_file=str(path),
        toc_fingerprint=fingerprint,
        unit_count=unit_count,
        chapter_count=chapter_count,
        section_count=section_count,
        toc_root=toc_root
    )


def extract_toc_hierarchy(root: etree._Element, collection_id: str = "") -> Tuple[TOCNode, int]:
    """
    Extract complete TOC from a collection XML root element.
    Detects and handles all 3 TOC patterns automatically.
    """
    content = root.find('.//col:content', NAMESPACES)
    if content is None:
        empty = TOCNode(node_id='root', node_type='root', title='', toc_order=0)
        return empty, 0

    direct_modules = content.findall('./col:module', NAMESPACES)
    subcollections = content.findall('./col:subcollection', NAMESPACES)

    if direct_modules and not subcollections:
        logger.info(f"Flat TOC: {len(direct_modules)} direct modules")
        return _extract_flat_toc(content, collection_id)

    if subcollections:
        first_sub = subcollections[0]
        sub_content = first_sub.find('./col:content', NAMESPACES)
        if sub_content is not None:
            nested = sub_content.findall('./col:subcollection', NAMESPACES)
            if nested:
                logger.info(f"Hierarchical TOC: {len(subcollections)} units")
                return _extract_hierarchical_toc(content, collection_id)
            else:
                logger.info(f"Chapter-only TOC: {len(subcollections)} chapters")
                return _extract_chapter_only_toc(content, collection_id)

    empty = TOCNode(node_id='root', node_type='root', title='', toc_order=0)
    return empty, 0


def _extract_flat_toc(content: etree._Element, collection_id: str) -> Tuple[TOCNode, int]:
    toc_order = 0
    sections = []
    for module_elem in content.findall('./col:module', NAMESPACES):
        title_elem = module_elem.find('./md:title', NAMESPACES)
        module_id = module_elem.get('document', '')
        if not module_id:
            continue
        toc_order += 1
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else f"Section {toc_order}"
        sections.append(TOCNode(
            node_id=f"{collection_id}_s_{toc_order}",
            node_type='section',
            title=title,
            number=str(toc_order),
            toc_order=toc_order,
            module_id=module_id
        ))
    root_node = TOCNode(node_id='root', node_type='root', title='', toc_order=0, children=sections)
    return root_node, toc_order


def _extract_chapter_only_toc(content: etree._Element, collection_id: str) -> Tuple[TOCNode, int]:
    toc_order = 0
    chapters = []
    ch_num = 0
    for ch_elem in content.findall('./col:subcollection', NAMESPACES):
        title_elem = ch_elem.find('./md:title', NAMESPACES)
        if title_elem is None:
            continue
        ch_num += 1
        ch_title = title_elem.text.strip() if title_elem.text else f"Chapter {ch_num}"
        toc_order += 1
        ch_node = TOCNode(
            node_id=f"{collection_id}_c_{toc_order}",
            node_type='chapter',
            title=ch_title,
            number=str(ch_num),
            toc_order=toc_order
        )
        ch_content = ch_elem.find('./col:content', NAMESPACES)
        if ch_content is not None:
            sec_num = 0
            for sec_elem in ch_content.findall('./col:module', NAMESPACES):
                sec_title_elem = sec_elem.find('./md:title', NAMESPACES)
                module_id = sec_elem.get('document', '')
                if not module_id:
                    continue
                sec_num += 1
                sec_title = sec_title_elem.text.strip() if sec_title_elem is not None and sec_title_elem.text else f"Section {sec_num}"
                toc_order += 1
                ch_node.children.append(TOCNode(
                    node_id=f"{collection_id}_s_{toc_order}",
                    node_type='section',
                    title=sec_title,
                    number=f"{ch_num}.{sec_num}",
                    toc_order=toc_order,
                    module_id=module_id
                ))
        if ch_node.children:
            chapters.append(ch_node)
    root_node = TOCNode(node_id='root', node_type='root', title='', toc_order=0, children=chapters)
    return root_node, toc_order


def _extract_hierarchical_toc(content: etree._Element, collection_id: str) -> Tuple[TOCNode, int]:
    toc_order = 0
    units = []
    ch_num = 0  # Global chapter counter across all units
    for unit_elem in content.findall('./col:subcollection', NAMESPACES):
        unit_title_elem = unit_elem.find('./md:title', NAMESPACES)
        if unit_title_elem is None:
            continue
        unit_title = unit_title_elem.text.strip() if unit_title_elem.text else "Untitled Unit"
        toc_order += 1
        unit_node = TOCNode(
            node_id=f"{collection_id}_u_{toc_order}",
            node_type='unit',
            title=unit_title,
            toc_order=toc_order
        )
        unit_content = unit_elem.find('./col:content', NAMESPACES)
        if unit_content is None:
            continue
        for ch_elem in unit_content.findall('./col:subcollection', NAMESPACES):
            ch_title_elem = ch_elem.find('./md:title', NAMESPACES)
            if ch_title_elem is None:
                continue
            ch_num += 1
            ch_title = ch_title_elem.text.strip() if ch_title_elem.text else f"Chapter {ch_num}"
            toc_order += 1
            ch_node = TOCNode(
                node_id=f"{collection_id}_c_{toc_order}",
                node_type='chapter',
                title=ch_title,
                number=str(ch_num),
                toc_order=toc_order
            )
            ch_content = ch_elem.find('./col:content', NAMESPACES)
            if ch_content is None:
                continue
            sec_num = 0
            for sec_elem in ch_content.findall('./col:module', NAMESPACES):
                sec_title_elem = sec_elem.find('./md:title', NAMESPACES)
                module_id = sec_elem.get('document', '')
                if not module_id:
                    continue
                sec_num += 1
                sec_title = sec_title_elem.text.strip() if sec_title_elem is not None and sec_title_elem.text else f"Section {sec_num}"
                toc_order += 1
                ch_node.children.append(TOCNode(
                    node_id=f"{collection_id}_s_{toc_order}",
                    node_type='section',
                    title=sec_title,
                    number=f"{ch_num}.{sec_num}",
                    toc_order=toc_order,
                    module_id=module_id
                ))
            if ch_node.children:
                unit_node.children.append(ch_node)
        if unit_node.children:
            units.append(unit_node)
    root_node = TOCNode(node_id='root', node_type='root', title='', toc_order=0, children=units)
    return root_node, toc_order


def _toc_fingerprint(toc_root: TOCNode) -> str:
    def serialize(node: TOCNode) -> str:
        parts = [node.node_type, node.title, str(node.toc_order)]
        for child in node.children:
            parts.append(serialize(child))
        return '|'.join(parts)
    return hashlib.sha256(serialize(toc_root).encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Content Extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_section_content(module_path: Path, repo_path: Path = None) -> SectionContent:
    """
    Extract complete content from a single CNXML module (index.cnxml).
    
    Args:
        module_path: Path to index.cnxml
        repo_path: Repo root (used to resolve media paths)
    """
    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_path}")

    tree = etree.parse(str(module_path))
    root = tree.getroot()

    module_id = module_path.parent.name

    title_elem = root.find('.//md:title', NAMESPACES)
    title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled"

    objectives = _extract_learning_objectives(root)
    terms = _extract_terms(root)
    blocks = _extract_content_blocks(root, module_path, repo_path)

    return SectionContent(
        module_id=module_id,
        title=title,
        learning_objectives=objectives,
        content_blocks=blocks,
        term_tags=terms
    )


def _get_text(elem: etree._Element) -> str:
    """Get all text content from an element, recursively."""
    if elem is None:
        return ''
    parts = []
    if elem.text:
        parts.append(elem.text.strip())
    for child in elem:
        if not isinstance(child.tag, str):  # skip Comments / PIs
            continue
        parts.append(_get_text(child))
        if child.tail:
            parts.append(child.tail.strip())
    return ' '.join(p for p in parts if p)


def _mathml_to_latex(math_elem: etree._Element) -> str:
    """Best-effort MathML → LaTeX extraction (extracts text content)."""
    if math_elem is None:
        return ''
    # Extract text content from MathML (approximate)
    text_parts = []
    for elem in math_elem.iter():
        if elem.text and elem.text.strip():
            text_parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            text_parts.append(elem.tail.strip())
    return ' '.join(text_parts)


def _resolve_image_path(src: str, module_path: Path, repo_path: Path = None) -> str:
    """Resolve image src (possibly relative ../../media/...) to a local path."""
    if not src:
        return ''
    # Most CNXML images use ../../media/filename relative to the module
    if src.startswith('../../media/'):
        filename = src.replace('../../media/', '')
        if repo_path:
            return str(repo_path / 'media' / filename)
        # Try resolving from module path
        media_path = module_path.parent.parent.parent / 'media' / filename
        return str(media_path)
    return src


def _extract_content_blocks(root: etree._Element, module_path: Path,
                             repo_path: Path = None) -> List[ContentBlock]:
    """
    Extract all content blocks from a CNXML module's <content> element.
    Handles: paragraph, equation, figure, table, example, exercise, note,
             definition, list, subsection.
    """
    blocks = []
    content = root.find('.//cnxml:content', NAMESPACES)
    if content is None:
        return blocks

    block_counter = [0]

    def next_id() -> str:
        block_counter[0] += 1
        return f"block_{block_counter[0]}"

    def process_element(elem: etree._Element, depth: int = 0):
        tag = elem.tag
        # Strip namespace
        local = tag.split('}')[-1] if '}' in tag else tag

        if local == 'para':
            text = _get_text(elem).strip()
            if text:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='paragraph',
                    text=text,
                    level=depth
                ))

        elif local == 'equation':
            math_elem = elem.find('.//m:math', NAMESPACES)
            if math_elem is not None:
                mathml_str = etree.tostring(math_elem, encoding='unicode')
                latex_str = _mathml_to_latex(math_elem)
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='equation',
                    mathml=mathml_str,
                    latex=latex_str
                ))

        elif local == 'figure':
            image_elem = elem.find('.//cnxml:image', NAMESPACES)
            caption_elem = elem.find('./cnxml:caption', NAMESPACES)
            image_path = ''
            if image_elem is not None:
                src = image_elem.get('src', '')
                image_path = _resolve_image_path(src, module_path, repo_path)
            caption = _get_text(caption_elem) if caption_elem is not None else ''
            blocks.append(ContentBlock(
                block_id=next_id(),
                block_type='figure',
                image_path=image_path,
                caption=caption
            ))

        elif local == 'table':
            title_elem = elem.find('./cnxml:title', NAMESPACES)
            tbl_title = _get_text(title_elem) if title_elem is not None else ''
            headers = []
            rows = []
            thead = elem.find('.//cnxml:thead', NAMESPACES)
            if thead is not None:
                for row in thead.findall('.//cnxml:row', NAMESPACES):
                    for entry in row.findall('./cnxml:entry', NAMESPACES):
                        headers.append(_get_text(entry))
            tbody = elem.find('.//cnxml:tbody', NAMESPACES)
            if tbody is not None:
                for row in tbody.findall('./cnxml:row', NAMESPACES):
                    row_data = [_get_text(e) for e in row.findall('./cnxml:entry', NAMESPACES)]
                    if row_data:
                        rows.append(row_data)
            if headers or rows:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='table',
                    title=tbl_title,
                    headers=headers,
                    rows=rows
                ))

        elif local == 'example':
            title_elem = elem.find('./cnxml:title', NAMESPACES)
            ex_title = _get_text(title_elem) if title_elem is not None else ''
            problem_elem = elem.find('.//cnxml:problem', NAMESPACES)
            solution_elem = elem.find('.//cnxml:solution', NAMESPACES)
            problem_text = _get_text(problem_elem) if problem_elem is not None else ''
            solution_text = _get_text(solution_elem) if solution_elem is not None else ''
            if problem_text or solution_text:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='example',
                    title=ex_title,
                    problem=problem_text,
                    solution=solution_text
                ))

        elif local == 'exercise':
            problem_elem = elem.find('.//cnxml:problem', NAMESPACES)
            solution_elem = elem.find('.//cnxml:solution', NAMESPACES)
            problem_text = _get_text(problem_elem) if problem_elem is not None else ''
            solution_text = _get_text(solution_elem) if solution_elem is not None else ''
            if problem_text:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='exercise',
                    problem=problem_text,
                    solution=solution_text
                ))

        elif local == 'note':
            note_class = elem.get('class', elem.get('type', 'note'))
            title_elem = elem.find('./cnxml:title', NAMESPACES)
            note_title = _get_text(title_elem) if title_elem is not None else ''
            # Get text excluding sub-elements like title
            text_parts = []
            for child in elem:
                if not isinstance(child.tag, str):  # skip Comments / PIs
                    continue
                child_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if child_local not in ('title',):
                    text_parts.append(_get_text(child))
            note_text = ' '.join(p for p in text_parts if p)
            if not note_text:
                note_text = _get_text(elem)
            if note_text or note_title:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='note',
                    note_type=note_class,
                    title=note_title,
                    text=note_text
                ))

        elif local == 'list':
            list_type = 'numbered' if elem.get('list-type') == 'enumerated' else 'bullet'
            items = []
            for item in elem.findall('./cnxml:item', NAMESPACES):
                item_text = _get_text(item)
                if item_text:
                    items.append(item_text)
            if items:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='list',
                    list_type=list_type,
                    items=items
                ))

        elif local == 'definition':
            term_elem = elem.find('./cnxml:term', NAMESPACES)
            meaning_elem = elem.find('./cnxml:meaning', NAMESPACES)
            term_text = _get_text(term_elem) if term_elem is not None else ''
            meaning_text = _get_text(meaning_elem) if meaning_elem is not None else ''
            if term_text:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='definition',
                    term=term_text,
                    meaning=meaning_text
                ))

        elif local == 'section':
            title_elem = elem.find('./cnxml:title', NAMESPACES)
            sec_title = _get_text(title_elem) if title_elem is not None else ''
            # Subsection: inject as a subsection block then recurse
            if sec_title:
                blocks.append(ContentBlock(
                    block_id=next_id(),
                    block_type='subsection',
                    title=sec_title,
                    level=depth + 1
                ))
            # Recurse into section content
            for child in elem:
                if not isinstance(child.tag, str):  # skip Comments / PIs
                    continue
                process_element(child, depth + 1)

        else:
            # For other elements, recurse into children
            for child in elem:
                if not isinstance(child.tag, str):  # skip Comments / PIs
                    continue
                process_element(child, depth)

    # Process all direct children of <content>
    for elem in content:
        if not isinstance(elem.tag, str):  # skip Comments / PIs
            continue
        process_element(elem, depth=0)

    return blocks


def _extract_learning_objectives(root: etree._Element) -> List[str]:
    """Extract learning objectives from section XML."""
    objectives = []
    # Pattern 1: section titled "Learning Objectives"
    for section in root.findall('.//cnxml:section', NAMESPACES):
        title_elem = section.find('./cnxml:title', NAMESPACES)
        if title_elem is not None and title_elem.text and 'learning objective' in title_elem.text.lower():
            for item in section.findall('.//cnxml:item', NAMESPACES):
                text = _get_text(item).strip()
                if text and text not in objectives:
                    objectives.append(text)
    # Pattern 2: note with class="learning-objectives"
    for note in root.findall('.//cnxml:note', NAMESPACES):
        cls = note.get('class', note.get('type', ''))
        if 'learning-objective' in cls.lower():
            for item in note.findall('.//cnxml:item', NAMESPACES):
                text = _get_text(item).strip()
                if text and text not in objectives:
                    objectives.append(text)
    # Pattern 3: <md:abstract> containing a list (modern OpenStax format)
    if not objectives:
        abstract = root.find('.//md:abstract', NAMESPACES)
        if abstract is not None:
            for item in abstract.findall('.//cnxml:item', NAMESPACES):
                text = _get_text(item).strip()
                if text and text not in objectives:
                    objectives.append(text)
    return objectives


def _extract_terms(root: etree._Element) -> List[str]:
    """Extract <term> tags from section."""
    terms = set()
    for term_elem in root.findall('.//cnxml:term', NAMESPACES):
        if term_elem.text:
            terms.add(term_elem.text.strip())
    return sorted(list(terms))
