# Changelog

All notable changes to GetBooks are documented here.

---

## [1.1.0] — 2026-03-09

### Fixed
- **Hierarchical TOC chapter numbering** (`cnxml_parser.py`): The global chapter counter
  was reset to 0 for each Unit in three-level (Unit→Chapter→Section) books such as
  Biology 2e. All first chapters in every Unit were assigned number "1". Counter is now
  global across units, producing correct sequential chapter numbers (1, 2, 3…).

- **Learning objectives extraction** (`cnxml_parser.py`): Modern OpenStax repos store
  learning objectives in `<md:abstract>` → `<cnxml:list>` rather than in a
  `<cnxml:section>` titled "Learning Objectives". Added Pattern 3 to
  `_extract_learning_objectives()` to cover this format.

- **Section titles from module CNXML** (`book_reader.py`): Modern OpenStax collection
  XML files do not embed `<md:title>` inside `<col:module>` elements. Section titles
  therefore fell back to "Section N" placeholders. `load_content()` now propagates the
  actual title from the module's CNXML file back to the TOC node after content loading.

### Added
- **`--pull-existing` flag** (`get_books.py`): Runs `git pull --ff-only` on all repos
  already present in `openstax_mirror/` without requiring a GitHub API token. Useful
  for routine updates when the token has expired or is unavailable.
  Result on first run: 27 repos updated, 3 already current, 0 failed.

- **Comprehensive README** (`README.md`): Full API reference covering all public
  functions, data classes, CLI flags, configuration options, series detection, JSON
  format spec, integration with SlideCreationSystem, and troubleshooting guide.

- **Hardened `.gitignore`**: Added patterns for credentials (`*.pem`, `*.key`,
  `.github_token`, `*.token`), editor artifacts (`.idea/`, `.vscode/`), and
  temporary files (`tmp/`, `temp/`, `*.tmp`, `*.bak`).

### Validated (Chunk C end-to-end)
- Biology 2e Chapter 1 → 3 sections → 148 ContentElements → **41 Gemini prompt files**
- University Physics Volume 1 Chapter 1 → 8 sections → 274 elements → **83 prompts**
- Chemistry 2e Chapter 1 → 7 sections → 309 elements → **78 prompts**
- All **72 tests pass** (GetBooks) + **21 tests pass** (SlideCreationSystem adapter)

---

## [1.0.0] — 2026-03-09

### Added
- **`get_books.py`**: Mirror manager — discovers OpenStax repos via GitHub API and
  clones / pulls them. Stripped port of `Books/GetBooks.py` with all curriculum and
  standards logic removed. Supports `--incremental`, `--dry-run`, `--check-updates`,
  `--stats`, `--verbose`.

- **`cnxml_parser.py`**: CNXML parser for both TOC (collection.xml) and content
  (modules/mXXXXX/index.cnxml). Handles all three TOC patterns (hierarchical,
  chapter-only, flat) and all ten content element types (paragraph, equation, figure,
  table, example, exercise, note, list, definition, subsection).

- **`series_resolver.py`**: Groups related books into series by volume number extracted
  from titles. Handles both bundle repos (multiple collection.xml in one repo) and
  separate-volume repos (University Physics Volumes 1/2/3).

- **`book_reader.py`**: Public API — `BookReader`, `Book`, `Section`. Provides
  `iter_sections()`, `get_chapter_sections()`, `get_section()`,
  `export_section_json()`, `export_chapter_json()`.

- **`json_exporter.py`**: Serialises `Book` objects to the canonical JSON format
  consumed by SlideCreationSystem's `openstax_adapter.py`.

- **`tests/`**: 72-test suite across 6 files covering all modules.

- **`openstax_books.md`**, **`openstax_config.json`**: Reference list and configuration
  (copied from `Books/`).

- **`requirements.txt`**: `PyGithub >= 2.8.0`, `lxml >= 5.0.0`, `requests >= 2.32.0`.

- **`progress.json`**: Implementation chunk tracker.

### Mirror
- 30 OpenStax repos cloned (27 `openstax_osbooks-*`, 3 `cnx-user-books_cnxbook-*`)
- 49 books across 10+ subjects
- Content current as of 2026-03-09

---

## Format

Versions follow [Semantic Versioning](https://semver.org/). Dates are UTC.
