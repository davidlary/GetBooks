# GetBooks

Maintains an up-to-date local mirror of all OpenStax CNXML repositories and provides a
robust API to read any section/chapter from any book (including multipart and bundle books).
Output is structured JSON consumed by SlideCreationSystem.

## Architecture

```
OpenStax GitHub repos
        ↓  (git clone / git pull via PyGithub)
openstax_mirror/         (local mirror, excluded from git)
        ↓  (cnxml_parser.py reads collection.xml + modules/)
book_reader.py           (public API: Book → Chapter → Section → ContentBlocks)
        ↓  (json_exporter.py serialises to structured JSON)
section_content.json
```

## Quick Start

```bash
pip install -r requirements.txt

# Mirror all OpenStax repos
python get_books.py

# Export a section to JSON
python -c "
from book_reader import BookReader
r = BookReader('openstax_mirror/')
r.export_section_json('University Physics Volume 1', 4, 2, 'section_4_2.json')
"
```

## Modules

| File | Purpose |
|------|---------|
| `get_books.py` | Mirror update — clone/pull all OpenStax repos via GitHub API |
| `cnxml_parser.py` | CNXML parsing — TOC hierarchy + all content element types |
| `series_resolver.py` | Bundle + volume detection and ordering |
| `book_reader.py` | Public API — `BookReader`, `Book`, section iteration |
| `json_exporter.py` | Serialise Book objects to structured JSON |

## Requirements

- Python 3.9+
- See `requirements.txt`

## Mirror Structure

After running `get_books.py`:
```
openstax_mirror/
  openstax_osbooks-chemistry-bundle/
    collections/
      chemistry-2e.collection.xml
      chemistry-atoms-first-2e.collection.xml
    modules/
      m68662/index.cnxml
      ...
    media/
  cnx-user-books_cnxbook-university-physics-volume-1/
    collections/
      university-physics-volume-1.collection.xml
    modules/
      m58268/index.cnxml
      ...
```

## JSON Output Format

```json
{
  "book": "University Physics Volume 1",
  "series": "University Physics",
  "volume": 1,
  "subject": "physics",
  "level": "undergraduate",
  "chapter": {"number": 4, "title": "Motion in Two and Three Dimensions"},
  "section": {"number": "4.2", "title": "Acceleration Vector", "toc_order": 42},
  "learning_objectives": ["Describe...", "Calculate..."],
  "content": [
    {"type": "paragraph", "text": "..."},
    {"type": "equation", "mathml": "<math>...", "latex": "\\vec{a} = ..."},
    {"type": "figure", "image_path": "media/CNX_UPhysics_04_02.jpg", "caption": "..."},
    {"type": "example", "title": "Finding Acceleration", "problem": "...", "solution": "..."},
    {"type": "note", "note_type": "everyday-connection", "title": "...", "text": "..."},
    {"type": "table", "title": "...", "headers": ["Col1","Col2"], "rows": [["a","b"]]},
    {"type": "definition", "term": "acceleration", "meaning": "..."}
  ]
}
```
