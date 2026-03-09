"""
Tests for openstax_mirror/ directory structure.

Verifies all 29+ repos are present and have valid git repos.
Uses real data from openstax_mirror/.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

MIRROR_DIR = Path(__file__).parent.parent / "openstax_mirror"

EXPECTED_REPOS = [
    "cnx-user-books_cnxbook-university-physics-volume-1",
    "cnx-user-books_cnxbook-university-physics-volume-2",
    "cnx-user-books_cnxbook-university-physics-volume-3",
    "openstax_osbooks-biology-bundle",
    "openstax_osbooks-calculus-bundle",
    "openstax_osbooks-chemistry-bundle",
    "openstax_osbooks-physics",
    "openstax_osbooks-microbiology",
    "openstax_osbooks-introduction-philosophy",
    "openstax_osbooks-psychology",
]


@pytest.fixture(scope="module")
def mirror_repos():
    """Return list of repo dirs actually present."""
    if not MIRROR_DIR.exists():
        pytest.skip(f"Mirror not yet copied to {MIRROR_DIR}")
    return [
        d for d in MIRROR_DIR.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ]


def test_mirror_directory_exists():
    """Mirror directory must exist."""
    assert MIRROR_DIR.exists(), f"Mirror dir missing: {MIRROR_DIR}"


def test_minimum_repo_count(mirror_repos):
    """At least 29 repos must be present."""
    assert len(mirror_repos) >= 29, \
        f"Expected >=29 repos, found {len(mirror_repos)}"


def test_expected_repos_present(mirror_repos):
    """All expected repos must be present."""
    repo_names = {r.name for r in mirror_repos}
    for expected in EXPECTED_REPOS:
        assert expected in repo_names, f"Missing expected repo: {expected}"


def test_repos_have_git_dir(mirror_repos):
    """Every repo dir must have a .git subdirectory."""
    for repo in mirror_repos:
        assert (repo / '.git').exists(), f"Missing .git in {repo.name}"


def test_repos_have_collections_dir(mirror_repos):
    """Every repo must have a collections/ or modules/ directory."""
    for repo in mirror_repos:
        has_collections = (repo / 'collections').exists()
        has_modules = (repo / 'modules').exists()
        assert has_collections or has_modules, \
            f"No collections/ or modules/ in {repo.name}"


def test_repos_have_modules(mirror_repos):
    """Every repo must have at least one module."""
    for repo in mirror_repos:
        modules_dir = repo / 'modules'
        if not modules_dir.exists():
            continue
        modules = [m for m in modules_dir.iterdir() if m.is_dir()]
        assert len(modules) > 0, f"No modules in {repo.name}"


def test_chemistry_bundle_has_two_collections(mirror_repos):
    """Chemistry bundle repo must have exactly 2 collection.xml files."""
    chem = next((r for r in mirror_repos
                 if 'chemistry-bundle' in r.name), None)
    if chem is None:
        pytest.skip("Chemistry bundle not in mirror")
    col_files = list((chem / 'collections').glob('*.collection.xml'))
    assert len(col_files) == 2, \
        f"Expected 2 chemistry collection files, found {len(col_files)}: {col_files}"


def test_university_physics_three_repos(mirror_repos):
    """University Physics must have 3 separate repos (vol 1, 2, 3)."""
    up_repos = [r for r in mirror_repos
                if 'university-physics-volume' in r.name]
    assert len(up_repos) == 3, \
        f"Expected 3 University Physics volume repos, found {len(up_repos)}"
