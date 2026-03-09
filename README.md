# GetBooks

Maintains an up-to-date local mirror of all OpenStax CNXML repositories and provides a
robust API to read any section/chapter from any book (including multipart and bundle books).
Output is structured JSON consumed by SlideCreationSystem.

## Architecture

```
OpenStax GitHub repos (openstax + cnx-user-books)
        │
        ▼  git clone / git pull
openstax_mirror/          ← local mirror (~12 GB), gitignored
        │
        ▼  cnxml_parser.py reads collection.xml + modules/
book_reader.py            ← public API: BookReader → Book → Section → ContentBlocks
        │
        ▼  json_exporter.py serialises
section.json / chapter.json
        │
        ▼  SlideCreationSystem/src/…/openstax_adapter.py
List[ContentElement]      ← native SlideCreationSystem type
        │
        ▼  unchanged pipeline stages 2-8
output/prompts/chapter_NN/slide_NNN.md  →  Gemini 4K slides
```

---

## Quick Start

```bash
pip install -r requirements.txt

# 1. Mirror / update all OpenStax repos (first run clones, subsequent pulls only changes)
python get_books.py

# 2. List all available books
python -c "
from book_reader import BookReader
r = BookReader('openstax_mirror/')
for b in r.get_all_books():
    print(b.title)
"

# 3. Export a specific section to JSON
python -c "
from book_reader import BookReader
r = BookReader('openstax_mirror/')
r.export_section_json('University Physics Volume 1', 4, 2, 'section_4_2.json')
"

# 4. Export a full chapter to JSON (list of sections)
python -c "
from book_reader import BookReader
r = BookReader('openstax_mirror/')
r.export_chapter_json('Chemistry 2e', 1, 'chemistry_ch1.json')
"
```

---

## Module Reference

### `get_books.py` — Mirror Management

Maintains a local mirror of all OpenStax repositories. Wraps PyGithub + `git` for
discovery, cloning, and pulling.

```bash
# Full update (discover new repos + pull all changes)
python get_books.py

# Pull only already-cloned repos (no GitHub API needed)
python get_books.py --pull-existing

# Incremental: only process repos that have upstream changes
python get_books.py --incremental

# Check which repos need updates (dry-run, no changes)
python get_books.py --check-updates

# Preview what would be cloned without doing it
python get_books.py --dry-run

# Verbose logging
python get_books.py --verbose

# Use custom config file
python get_books.py --config my_config.json
```

**Environment variables:**

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | GitHub personal access token for higher API rate limits |

Without a token: 60 API requests/hour (usually sufficient for `--pull-existing`).

**Key methods:**

```python
from get_books import OpenStaxMirror

mirror = OpenStaxMirror(config_path="openstax_config.json")
stats = mirror.update_mirror()          # Full update
stats = mirror.pull_existing_mirror()  # Pull without GitHub API
status = mirror.check_updates()        # Non-destructive status report
```

---

### `cnxml_parser.py` — CNXML Parsing

Parses OpenStax CNXML content (both collection TOC and individual module files).

**Key functions:**

```python
from cnxml_parser import (
    find_collection_files,   # Discover *.collection.xml in a repo
    parse_collection_xml,    # Parse collection → BookMetadata with full TOC
    extract_section_content, # Parse modules/mXXXXX/index.cnxml → SectionContent
    extract_toc_hierarchy,   # Detect and parse all 3 TOC patterns
)
```

**Data classes:**

```python
@dataclass
class BookMetadata:
    collection_id: str
    title: str
    education_level: str    # "undergraduate" | "high school"
    discipline: str         # "physics" | "chemistry" | "biology" | ...
    local_path: str         # Path to repo root
    collection_file: str    # Path to *.collection.xml
    toc_root: TOCNode       # Full TOC tree

@dataclass
class TOCNode:
    node_id: str
    node_type: str          # "root" | "unit" | "chapter" | "section"
    title: str
    number: str             # e.g. "4.2" for section, "4" for chapter
    toc_order: int          # Sequential number for sorting
    module_id: str          # CNXML module ID (sections only)
    children: List[TOCNode]

@dataclass
class SectionContent:
    module_id: str
    title: str              # From <md:title> in module file
    learning_objectives: List[str]
    content_blocks: List[ContentBlock]
    term_tags: List[str]

@dataclass
class ContentBlock:
    block_id: str
    block_type: str         # One of 10 types (see below)
    # Type-specific fields:
    text: str               # paragraph, note
    mathml: str             # equation
    latex: str              # equation (best-effort)
    image_path: str         # figure
    caption: str            # figure
    title: str              # table, example, note, subsection
    headers: List[str]      # table
    rows: List[List[str]]   # table
    problem: str            # example, exercise
    solution: str           # example, exercise
    note_type: str          # note (e.g. "everyday-connection")
    list_type: str          # list ("bullet" | "numbered")
    items: List[str]        # list
    term: str               # definition
    meaning: str            # definition
    level: int              # subsection nesting depth
```

**Three TOC patterns (auto-detected):**

| Pattern | Structure | Example books |
|---------|-----------|---------------|
| Hierarchical | Unit → Chapter → Section | Biology 2e, University Physics |
| Chapter-only | Chapter → Section | Chemistry 2e, Calculus |
| Flat | Direct sections | Some legacy books |

**Bundle repos** (single git repo, multiple `*.collection.xml`): Calculus, Chemistry,
Biology, College Physics, College Algebra, Introductory Statistics, Prealgebra,
Principles of Accounting, Principles of Economics.

**Content elements extracted:**

| CNXML element | `block_type` |
|---|---|
| `<para>` | `"paragraph"` |
| `<equation>` + `<math>` | `"equation"` (MathML + best-effort LaTeX) |
| `<figure>` + `<image>` + `<caption>` | `"figure"` |
| `<table>` | `"table"` (headers + 2D rows) |
| `<example>` | `"example"` |
| `<exercise>` + `<problem>` + `<solution>` | `"exercise"` |
| `<note type="...">` | `"note"` |
| `<list>` | `"list"` (bullet or numbered) |
| `<definition>` | `"definition"` |
| nested `<section>` | `"subsection"` |

Learning objectives are extracted from three locations (in priority order):
1. `<cnxml:section>` with title containing "Learning Objectives"
2. `<cnxml:note class="learning-objectives">`
3. `<md:abstract>` → `<cnxml:list>` items (modern OpenStax format)

---

### `series_resolver.py` — Series Detection

Groups related books (volumes) into series.

```python
from series_resolver import detect_series, get_volume_number, is_standalone

books = reader.get_all_books()  # List[BookMetadata]
series = detect_series(books)   # List[Series]

for s in series:
    print(f"{s.name}: {len(s.volumes)} volumes")
    for vol in s.volumes:
        print(f"  Vol {get_volume_number(vol)}: {vol.title}")
```

Volume number extraction via regex patterns: `Volume N`, `Vol. N`, `Part N`.

**Known series:**

| Series | Volumes |
|--------|---------|
| University Physics | 1, 2, 3 (separate repos) |
| Calculus | 1, 2, 3 (bundle repo) |
| Principles of Accounting | 1, 2 (bundle) |
| Principles of Economics (macro/micro) | 2 books (bundle) |
| College Physics | 2e + AP Courses (bundle) |

---

### `book_reader.py` — Public API

The primary interface for reading OpenStax content.

```python
from book_reader import BookReader

reader = BookReader("openstax_mirror/")

# ── Book discovery ────────────────────────────────────────────
books = reader.get_all_books()          # List[BookMetadata], sorted by title
book  = reader.get_book("Chemistry 2e") # Book | None
all_series = reader.get_all_series()   # List[Series]
series = reader.get_series("University Physics")  # Series | None

# ── Section iteration ─────────────────────────────────────────
for section in book.iter_sections():   # Generator, toc_order sorted, content loaded
    data = book.to_section_dict(section)  # canonical JSON dict

# ── Chapter access ────────────────────────────────────────────
sections = book.get_chapter_sections(1)     # List[Section] for chapter 1
section  = book.get_section(4, 2)           # Section 4.2 | None

# ── Content loading ───────────────────────────────────────────
content = section.load_content(book.repo_path)  # SectionContent
print(section.section_title)   # After load_content() — uses actual module title
print(section.section_number)  # e.g. "4.2"
print(section.chapter_title)   # e.g. "Motion in Two and Three Dimensions"
print(section.toc_order)       # e.g. 42

# ── JSON export (convenience wrappers) ───────────────────────
reader.export_section_json("University Physics Volume 1", 4, 2, "sec_4_2.json")
reader.export_chapter_json("Chemistry 2e", 1, "chem_ch1.json")
```

**Section JSON dict format** (`book.to_section_dict(section)`):

```json
{
  "book": "University Physics Volume 1",
  "series": "University Physics",
  "volume": 1,
  "subject": "physics",
  "level": "undergraduate",
  "chapter": {"number": 4, "title": "Motion in Two and Three Dimensions"},
  "section": {"number": "4.2", "title": "Acceleration Vector", "toc_order": 42},
  "learning_objectives": [
    "Describe motion in two dimensions using vectors.",
    "Calculate the acceleration vector for a particle."
  ],
  "content": [
    {"type": "paragraph", "text": "In this section we study acceleration."},
    {"type": "equation", "mathml": "<math xmlns='...'><mi>a</mi></math>",
     "latex": "a = dv / dt"},
    {"type": "figure", "image_path": ".../media/CNX_UPhysics_04_02.jpg",
     "caption": "Acceleration diagram."},
    {"type": "table", "title": "Kinematic quantities",
     "headers": ["Quantity", "Symbol", "Units"],
     "rows": [["Acceleration", "a", "m/s²"], ["Velocity", "v", "m/s"]]},
    {"type": "example", "title": "Finding Acceleration",
     "problem": "A particle moves at 3 m/s. Find a.",
     "solution": "a = dv/dt = 0.5 m/s²"},
    {"type": "note", "note_type": "everyday-connection",
     "title": "Everyday Acceleration", "text": "You feel acceleration in a car."},
    {"type": "list", "list_type": "bullet",
     "items": ["Item one", "Item two", "Item three"]},
    {"type": "definition", "term": "acceleration",
     "meaning": "Rate of change of velocity."}
  ]
}
```

Chapter JSON is a list of section dicts (one per section).

---

### `json_exporter.py` — JSON Serialisation

Lower-level export functions used internally by `BookReader`.

```python
from json_exporter import export_section, export_chapter, write_json

data = export_section(section)          # dict matching spec above
data = export_chapter(chapter_sections) # List[dict]
write_json(data, "/tmp/output.json")    # writes with indent=2
```

---

## Integration with SlideCreationSystem

GetBooks JSON flows directly into the SlideCreationSystem via two new flags:

```bash
cd SlideCreationSystem/

# Option 1: Pass a pre-exported JSON file
python -m slide_creation_system.cli run \
  --openstax-json /tmp/chemistry_2e_ch1.json \
  --chapter-number 1

# Option 2: Auto-export directly from the mirror
python -m slide_creation_system.cli run \
  --openstax-book "University Physics Volume 1" \
  --chapter 4 \
  --section 2 \
  --mirror /path/to/openstax_mirror

# Option 3: Export an entire chapter
python -m slide_creation_system.cli run \
  --openstax-book "Chemistry 2e" \
  --chapter 1 \
  --mirror /path/to/openstax_mirror
```

**Injection point**: Between Stage 1 (LaTeX parse) and Stage 2 (semantic chunking) in
`pipeline.py`. All downstream stages (Bloom, Mayer, accessibility, prompt generation)
run unchanged.

**ContentElement mapping:**

| GetBooks JSON type | ContentElement.element_type | Notes |
|---|---|---|
| `paragraph` | `"paragraph"` | content = text |
| `equation` | `"equation"` | content = LaTeX; metadata has MathML |
| `figure` | `"figure"` | caption field set; content = image path |
| `table` | `"table"` | content = Markdown table; caption = title |
| `example` | `"paragraph"` | metadata `type="example"` |
| `exercise` | `"paragraph"` | metadata `type="exercise"` |
| `note` | `"paragraph"` | metadata `note_type="everyday-connection"` etc. |
| `list` | `"paragraph"` | bullet/numbered items as text |
| `definition` | `"paragraph"` | "**term**: meaning"; metadata `type="definition"` |
| section title | `"section"` | level=1; injected as first element |
| `learning_objectives` | `"section"` | level=0, label="learning_objectives" |
| `subsection` | `"section"` | metadata `type="subsection"` |

---

## Configuration

**`openstax_config.json`** — Controls `get_books.py` discovery:

```json
{
  "search_queries": {
    "openstax_main": "org:openstax osbooks- in:name",
    "cnx_books": "org:cnx-user-books cnxbook in:name",
    "additional_orgs": []
  },
  "books_reference_file": "openstax_books.md",
  "clone_timeout_seconds": 300,
  "subject_mapping": {
    "Mathematics": ["algebra", "calculus", "statistics"],
    "Biology": ["biology", "anatomy", "physiology"],
    "Physics": ["physics", "university physics"]
  }
}
```

To add a new publisher, append to `additional_orgs`.

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Individual test files
python -m pytest tests/test_mirror.py -v         # 8 tests: mirror structure
python -m pytest tests/test_get_books.py -v      # 8 tests: discovery (mocked PyGithub)
python -m pytest tests/test_cnxml_parser.py -v   # 15 tests: TOC + content extraction
python -m pytest tests/test_series_resolver.py -v # 12 tests: series/volume grouping
python -m pytest tests/test_book_reader.py -v    # 15 tests: public API
python -m pytest tests/test_json_exporter.py -v  # 11 tests: round-trip JSON
```

All tests use real data from `openstax_mirror/` except `test_get_books.py` (mocks GitHub API).

**Test status**: 72/72 passed.

---

## Mirror Structure

```
openstax_mirror/
  inventory.json                    ← book catalog
  inventory.md                      ← human-readable catalog
  effective_config.json             ← merged runtime config
  .getbooks_state.json              ← incremental update state

  openstax_osbooks-chemistry-bundle/
    collections/
      chemistry-2e.collection.xml   ← TOC for Chemistry 2e
      chemistry-atoms-first-2e.collection.xml
    modules/
      m68662/index.cnxml            ← Chapter intro
      m68663/index.cnxml            ← Section 1.1
      ...
    media/
      CNX_Chem_01_01.jpg
      ...

  cnx-user-books_cnxbook-university-physics-volume-1/
    collections/
      university-physics-volume-1.collection.xml
    modules/
      m58268/index.cnxml
      ...
```

30 repos total: 27 `openstax_osbooks-*`, 3 `cnx-user-books_cnxbook-*`.

---

## Troubleshooting

**GitHub rate limit errors (60 req/hr without token)**
```bash
export GITHUB_TOKEN="ghp_your_token_here"
python get_books.py
```

**Expired GitHub token → 401 Bad Credentials**
→ Generate new token at https://github.com/settings/tokens (needs `public_repo` scope)
→ Or use `--pull-existing` to skip GitHub API entirely

**Clone timeout**
→ Increase `clone_timeout_seconds` in `openstax_config.json`

**Missing section titles (shows "Section N")**
→ Titles are loaded lazily from module CNXML when content is accessed
→ Call `section.load_content(book.repo_path)` before reading `section.section_title`

**Zero content blocks**
→ `section.to_dict()` requires `repo_path` parameter: `section.to_dict(repo_path=book.repo_path)`

---

## Files

| File | Purpose |
|------|---------|
| `get_books.py` | Mirror update — clone/pull all OpenStax repos via GitHub API |
| `cnxml_parser.py` | CNXML parsing — TOC hierarchy + all 10 content element types |
| `series_resolver.py` | Bundle + volume detection and ordering |
| `book_reader.py` | Public API — `BookReader`, `Book`, `Section` |
| `json_exporter.py` | Serialise Book objects to structured JSON |
| `openstax_books.md` | Reference list of all 46+ OpenStax books |
| `openstax_config.json` | Discovery and subject-mapping configuration |
| `requirements.txt` | Python dependencies |
| `progress.json` | Implementation progress tracker |
| `tests/` | 72-test suite |

**Gitignored (never committed):**
- `openstax_mirror/` (~12 GB of CNXML repos)
- `*.log`
- `__pycache__/`
- `.env`, secrets

---

## Requirements

- Python 3.9+
- `PyGithub >= 2.8.0` — GitHub API discovery
- `lxml >= 5.0.0` — Fast XML parsing
- `requests >= 2.32.0` — HTTP utilities
- `git` command-line tool (for clone/pull)

Install: `pip install -r requirements.txt`
