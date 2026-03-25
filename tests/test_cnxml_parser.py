"""
Tests for cnxml_parser.py.

Uses real CNXML files from openstax_mirror/ to verify:
- All 3 TOC patterns (hierarchical, chapter-only, flat)
- Bundle detection (multiple collection.xml in one repo)
- Content block extraction (all element types)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from cnxml_parser import (
    BookMetadata,
    SectionContent,
    TOCNode,
    find_collection_files,
    parse_collection_xml,
    extract_section_content,
    extract_toc_hierarchy,
    identify_discipline,
)

MIRROR = Path(__file__).parent.parent / "openstax_mirror"


def _mirror_skip():
    if not MIRROR.exists():
        pytest.skip("openstax_mirror not present")


# ─── Discipline detection ─────────────────────────────────────────────────────

class TestIdentifyDiscipline:
    def test_physics(self):
        assert identify_discipline("openstax_osbooks-physics") == "physics"

    def test_chemistry(self):
        assert identify_discipline("openstax_osbooks-chemistry-bundle") == "chemistry"

    def test_biology(self):
        assert identify_discipline("openstax_osbooks-biology-bundle") == "biology"

    def test_calculus(self):
        assert identify_discipline("openstax_osbooks-calculus-bundle") == "mathematics"

    def test_university_physics(self):
        assert identify_discipline("cnx-user-books_cnxbook-university-physics-volume-1") == "physics"

    def test_unknown(self):
        assert identify_discipline("openstax_osbooks-some-other-repo") == "unknown"


# ─── Bundle detection ─────────────────────────────────────────────────────────

class TestFindCollectionFiles:
    def test_chemistry_bundle_has_two_files(self):
        _mirror_skip()
        chem_repo = MIRROR / "openstax_osbooks-chemistry-bundle"
        if not chem_repo.exists():
            pytest.skip("Chemistry bundle not in mirror")
        files = find_collection_files(chem_repo)
        assert len(files) == 2, f"Expected 2 files, got: {files}"
        names = [f.name for f in files]
        assert any('chemistry-2e' in n for n in names)
        assert any('atoms-first' in n for n in names)

    def test_university_physics_has_one_file(self):
        _mirror_skip()
        up1 = MIRROR / "cnx-user-books_cnxbook-university-physics-volume-1"
        if not up1.exists():
            pytest.skip()
        files = find_collection_files(up1)
        assert len(files) == 1

    def test_calculus_bundle_has_multiple_files(self):
        _mirror_skip()
        calc = MIRROR / "openstax_osbooks-calculus-bundle"
        if not calc.exists():
            pytest.skip()
        files = find_collection_files(calc)
        assert len(files) >= 2, f"Expected >=2 Calculus collections, got: {files}"


# ─── TOC Parsing ─────────────────────────────────────────────────────────────

class TestParseCollectionXml:
    def test_hierarchical_toc_university_physics(self):
        """University Physics Vol 1 has unit->chapter->section structure."""
        _mirror_skip()
        col_file = MIRROR / "cnx-user-books_cnxbook-university-physics-volume-1" \
                          / "collections" / "university-physics-volume-1.collection.xml"
        if not col_file.exists():
            pytest.skip()
        bm = parse_collection_xml(col_file)
        assert bm.title == "University Physics Volume 1"
        assert bm.unit_count > 0, "Should have units"
        assert bm.chapter_count > 0
        assert bm.section_count > 0
        assert bm.discipline == "physics"
        # TOC root should have unit children
        assert bm.toc_root is not None
        assert any(c.node_type == 'unit' for c in bm.toc_root.children)

    def test_chapter_only_toc_chemistry(self):
        """Chemistry 2e has chapter->section structure (no units)."""
        _mirror_skip()
        chem = MIRROR / "openstax_osbooks-chemistry-bundle" / "collections"
        col_files = list(chem.glob("chemistry-2e*.collection.xml")) if chem.exists() else []
        if not col_files:
            pytest.skip()
        bm = parse_collection_xml(col_files[0])
        assert 'Chemistry' in bm.title
        assert bm.chapter_count > 0
        assert bm.unit_count == 0, "Chemistry should have no units"
        assert bm.toc_root is not None
        assert any(c.node_type == 'chapter' for c in bm.toc_root.children)

    def test_toc_fingerprint_is_stable(self):
        """Same collection.xml parsed twice should yield same fingerprint."""
        _mirror_skip()
        col_file = MIRROR / "cnx-user-books_cnxbook-university-physics-volume-1" \
                          / "collections" / "university-physics-volume-1.collection.xml"
        if not col_file.exists():
            pytest.skip()
        bm1 = parse_collection_xml(col_file)
        bm2 = parse_collection_xml(col_file)
        assert bm1.toc_fingerprint == bm2.toc_fingerprint

    def test_toc_order_is_sequential(self):
        """All toc_order values in sections should be sequential and unique."""
        _mirror_skip()
        col_file = MIRROR / "cnx-user-books_cnxbook-university-physics-volume-1" \
                          / "collections" / "university-physics-volume-1.collection.xml"
        if not col_file.exists():
            pytest.skip()
        bm = parse_collection_xml(col_file)
        toc_orders = []

        def collect_orders(node: TOCNode):
            toc_orders.append(node.toc_order)
            for child in node.children:
                collect_orders(child)

        for child in bm.toc_root.children:
            collect_orders(child)

        non_zero = [o for o in toc_orders if o > 0]
        assert len(non_zero) == len(set(non_zero)), "toc_order values must be unique"
        assert non_zero == sorted(non_zero), "toc_order values must be sequential"


# ─── Content Extraction ───────────────────────────────────────────────────────

class TestExtractSectionContent:
    def _get_module(self, repo_name, module_id) -> Path:
        _mirror_skip()
        path = MIRROR / repo_name / "modules" / module_id / "index.cnxml"
        if not path.exists():
            pytest.skip(f"Module not found: {path}")
        return path

    def test_extracts_title(self):
        """Section content should have a non-empty title."""
        module_path = self._get_module(
            "cnx-user-books_cnxbook-university-physics-volume-1", "m58268"
        )
        content = extract_section_content(module_path)
        assert content.title, "Section should have a title"

    def test_extracts_paragraphs(self):
        """Should extract at least one paragraph block."""
        module_path = self._get_module(
            "cnx-user-books_cnxbook-university-physics-volume-1", "m58268"
        )
        content = extract_section_content(module_path)
        para_blocks = [b for b in content.content_blocks if b.block_type == 'paragraph']
        assert len(para_blocks) > 0

    def test_extracts_figures(self):
        """Introduction modules typically have a figure."""
        module_path = self._get_module(
            "cnx-user-books_cnxbook-university-physics-volume-1", "m58268"
        )
        content = extract_section_content(module_path)
        fig_blocks = [b for b in content.content_blocks if b.block_type == 'figure']
        assert len(fig_blocks) > 0

    def test_chemistry_extracts_learning_objectives(self):
        """Chemistry sections typically have learning objectives."""
        chem_repo = MIRROR / "openstax_osbooks-chemistry-bundle"
        if not chem_repo.exists():
            pytest.skip()
        # Find first non-introduction module
        modules_dir = chem_repo / "modules"
        modules = sorted(modules_dir.iterdir())
        for mod_dir in modules[5:15]:  # skip very first modules
            mod_path = mod_dir / "index.cnxml"
            if mod_path.exists():
                content = extract_section_content(mod_path, chem_repo)
                if content.learning_objectives:
                    assert isinstance(content.learning_objectives, list)
                    assert len(content.learning_objectives) > 0
                    return
        # If no section with LOs found, that's acceptable
        pytest.skip("No chemistry section with learning objectives found in tested modules")

    def test_content_blocks_are_typed(self):
        """All content blocks should have valid block_type."""
        module_path = self._get_module(
            "cnx-user-books_cnxbook-university-physics-volume-1", "m58268"
        )
        content = extract_section_content(module_path)
        valid_types = {
            'paragraph', 'equation', 'figure', 'table', 'example',
            'exercise', 'note', 'list', 'definition', 'subsection'
        }
        for block in content.content_blocks:
            assert block.block_type in valid_types, \
                f"Unknown block_type: {block.block_type}"


# ─── Comment / PI node robustness ─────────────────────────────────────────────

class TestCommentAndPINodes:
    """Regression tests: lxml Comment/PI nodes must never crash the parser.

    lxml's etree.Comment and etree.ProcessingInstruction objects have `.tag`
    attributes that return cython callables instead of strings.  Any code that
    does `'}' in child.tag` without a type-guard will raise
    "argument of type 'cython_function_or_method' is not iterable".
    These tests create synthetic CNXML with embedded comments/PIs and verify
    that `extract_section_content` completes without error.
    """

    def _write_cnxml(self, tmp_path, body_xml: str) -> Path:
        """Write a minimal CNXML file with the supplied body fragment."""
        cnxml = f"""<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="http://cnx.rice.edu/cnxml"
          xmlns:m="http://www.w3.org/1998/Math/MathML"
          xmlns:md="http://cnx.rice.edu/mdml">
  <title>Test Section</title>
  <metadata xmlns:md="http://cnx.rice.edu/mdml">
    <md:content-id>m00000</md:content-id>
    <md:title>Test Section</md:title>
  </metadata>
  <content>
{body_xml}
  </content>
</document>"""
        path = tmp_path / "index.cnxml"
        path.write_text(cnxml, encoding="utf-8")
        return path

    def test_html_comment_in_paragraph_does_not_crash(self, tmp_path):
        """HTML comment node inside a <para> must be silently skipped."""
        body = """    <para id="p1">Before comment <!-- this is a comment --> after comment.</para>"""
        path = self._write_cnxml(tmp_path, body)
        content = extract_section_content(path)
        assert content is not None
        assert content.title == "Test Section"
        # Paragraph text should be extractable (comment text is irrelevant)
        para_blocks = [b for b in content.content_blocks if b.block_type == 'paragraph']
        assert len(para_blocks) >= 1

    def test_html_comment_in_note_does_not_crash(self, tmp_path):
        """Comment node inside a <note> (the m66430 failure mode) must not crash.

        Biology 2e module m66430 has HTML comments inside <note> elements.
        Before the fix, this raised:
          TypeError: argument of type 'cython_function_or_method' is not iterable
        """
        body = """    <note id="note1" class="visual-connection">
      <!-- Figure 2.5 -->
      <para id="p1">Water is a polar molecule.</para>
    </note>"""
        path = self._write_cnxml(tmp_path, body)
        content = extract_section_content(path)
        assert content is not None
        assert content.title == "Test Section"

    def test_processing_instruction_in_section_does_not_crash(self, tmp_path):
        """Processing instruction node inside a <section> must be silently skipped."""
        body = """    <section id="s1">
      <title>Subsection</title>
      <?some-pi target?>
      <para id="p1">A paragraph in a section.</para>
    </section>"""
        path = self._write_cnxml(tmp_path, body)
        content = extract_section_content(path)
        assert content is not None

    def test_multiple_comments_across_elements_do_not_crash(self, tmp_path):
        """Multiple HTML comments scattered through various elements must all be skipped."""
        body = """    <!-- section-level comment -->
    <para id="p1"><!-- inline comment -->Some text.</para>
    <para id="p2">More text<!-- trailing comment -->.</para>
    <note id="note1">
      <!-- note comment -->
      <para id="p3">Note body.</para>
    </note>"""
        path = self._write_cnxml(tmp_path, body)
        content = extract_section_content(path)
        assert content is not None
        assert content.title == "Test Section"

    def test_biology_m66430_module_parses_without_error(self):
        """Regression: Biology 2e module m66430 (section 2.2) must parse cleanly.

        This is the specific module that caused PlaceholderDataError during
        Biology 2e Chapter 2 generation.  The module contains HTML comments
        inside <note> elements.
        """
        bio_module = (
            MIRROR
            / "openstax_osbooks-biology-bundle"
            / "modules"
            / "m66430"
            / "index.cnxml"
        )
        if not bio_module.exists():
            pytest.skip("Biology mirror not present")

        bio_repo = MIRROR / "openstax_osbooks-biology-bundle"
        content = extract_section_content(bio_module, bio_repo)

        assert content is not None
        # Title must be a real section title, NOT a placeholder like "Section 2"
        assert content.title, "Title should be non-empty"
        assert content.title not in ("Section 2", "Section", ""), (
            f"Got placeholder title: {content.title!r}"
        )

    def test_all_biology_chapter2_modules_parse_without_placeholder(self):
        """All Biology 2e chapter 2 modules should parse to non-placeholder titles.

        Exercises all modules referenced in chapter 2 of Biology 2e to catch
        any future Comment/PI node bugs before they cause generation failures.
        """
        bio_repo = MIRROR / "openstax_osbooks-biology-bundle"
        if not bio_repo.exists():
            pytest.skip("Biology mirror not present")

        col_files = list((bio_repo / "collections").glob("biology-2e*.collection.xml"))
        if not col_files:
            pytest.skip("Biology 2e collection.xml not found")

        bm = parse_collection_xml(col_files[0])

        # Find chapter 2 in the TOC (TOCNode uses .number attribute, not .chapter_number)
        ch2_node = None
        for node in (bm.toc_root.children if bm.toc_root else []):
            # Direct chapter node: number == "2"
            if node.node_type == 'chapter' and node.number == '2':
                ch2_node = node
                break
            # Unit node: search its chapter children
            if node.node_type == 'unit':
                for ch in node.children:
                    if ch.node_type == 'chapter' and ch.number == '2':
                        ch2_node = ch
                        break
                if ch2_node:
                    break

        if ch2_node is None:
            pytest.skip("Chapter 2 not found in Biology 2e TOC")

        # Collect all module paths in chapter 2
        def collect_modules(node):
            paths = []
            if node.module_id:
                p = bio_repo / "modules" / node.module_id / "index.cnxml"
                if p.exists():
                    paths.append((node.module_id, p))
            for child in node.children:
                paths.extend(collect_modules(child))
            return paths

        modules = collect_modules(ch2_node)
        assert len(modules) > 0, "Chapter 2 should have modules"

        placeholder_titles = {"Section 2", "Section", ""}
        failures = []
        for mod_id, mod_path in modules:
            try:
                content = extract_section_content(mod_path, bio_repo)
                if content.title in placeholder_titles:
                    failures.append(f"{mod_id}: placeholder title {content.title!r}")
            except Exception as exc:
                failures.append(f"{mod_id}: exception {exc!r}")

        assert not failures, (
            f"Biology 2e chapter 2 module parse failures:\n" + "\n".join(failures)
        )
