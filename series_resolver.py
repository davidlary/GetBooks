"""
Series Resolver for GetBooks

Detects multi-volume series among BookMetadata objects and orders volumes correctly.

Handles:
1. Bundle repos — multiple collection.xml in one repo (Calculus Vol 1/2/3)
2. Separate-volume repos — e.g. University Physics: 3 separate repos, same series
3. Standalone books — no series
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from cnxml_parser import BookMetadata


# Regex patterns for volume number extraction
_VOLUME_PATTERNS = [
    r'[Vv]olume\s+(\d+)',
    r'[Vv]ol\.\s*(\d+)',
    r'[Pp]art\s+(\d+)',
]

# Series whose ordering is pedagogical (not volume numbers).
# Derived from openstax_books.md naming conventions.
_PEDAGOGICAL_ORDER = {
    'prealgebra': 1,
    'elementary algebra': 2,
    'intermediate algebra': 3,
    'college algebra': 4,
    'precalculus': 5,
    'calculus': 6,
}


@dataclass
class Series:
    """A multi-volume series of books."""
    name: str                           # e.g. "University Physics"
    volumes: List[BookMetadata] = field(default_factory=list)  # ordered by volume number

    def __repr__(self):
        titles = [b.title for b in self.volumes]
        return f"Series(name='{self.name}', volumes={titles})"


def _extract_volume_number(title: str) -> Optional[int]:
    """Extract volume/part number from a book title. Returns None if not found."""
    for pattern in _VOLUME_PATTERNS:
        m = re.search(pattern, title)
        if m:
            return int(m.group(1))
    return None


def _strip_volume_indicator(title: str) -> str:
    """Return title with volume/part indicator removed."""
    result = title
    for pattern in _VOLUME_PATTERNS:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', result).strip().rstrip(',').strip()


def _pedagogical_order(title: str) -> Optional[int]:
    """Return ordering value for pedagogical sequences, or None."""
    tl = title.lower()
    for key, order in _PEDAGOGICAL_ORDER.items():
        if key in tl:
            return order
    return None


def detect_series(books: List[BookMetadata]) -> List[Series]:
    """
    Group books into series based on shared title prefix and volume numbering.

    Args:
        books: All BookMetadata objects from the mirror.

    Returns:
        List of Series objects, each with volumes sorted by volume number.
        Standalone books are not included.
    """
    # Group by stripped-title (potential series name)
    groups: Dict[str, List[BookMetadata]] = {}
    for book in books:
        stripped = _strip_volume_indicator(book.title)
        groups.setdefault(stripped, []).append(book)

    series_list: List[Series] = []
    for name, group in groups.items():
        if len(group) < 2:
            continue  # standalone book

        # Sort by volume number
        def sort_key(b: BookMetadata):
            vol = _extract_volume_number(b.title)
            if vol is not None:
                return vol
            # Pedagogical ordering as fallback
            ped = _pedagogical_order(b.title)
            if ped is not None:
                return ped
            return 999

        sorted_group = sorted(group, key=sort_key)
        series_list.append(Series(name=name, volumes=sorted_group))

    return series_list


def get_volume_number(book: BookMetadata) -> Optional[int]:
    """Return the volume number for a book, or None if not part of a numbered series."""
    return _extract_volume_number(book.title)


def is_standalone(book: BookMetadata, all_books: List[BookMetadata]) -> bool:
    """Return True if this book is not part of any multi-volume series."""
    stripped = _strip_volume_indicator(book.title)
    matches = [b for b in all_books if _strip_volume_indicator(b.title) == stripped]
    return len(matches) < 2
