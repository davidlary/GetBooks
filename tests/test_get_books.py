"""
Tests for get_books.py — mirror update logic.

GitHub API calls are mocked; only local filesystem operations are real.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from get_books import OpenStaxMirror, DEFAULT_CONFIG


@pytest.fixture
def tmp_mirror(tmp_path):
    """Provide a temp dir as the mirror directory."""
    mirror = tmp_path / "openstax_mirror"
    mirror.mkdir()
    return mirror


@pytest.fixture
def mirror(tmp_mirror):
    """OpenStaxMirror instance with temp dir, no GitHub token."""
    return OpenStaxMirror(
        mirror_dir=str(tmp_mirror),
        config_file="nonexistent_config.json",  # uses defaults
        dry_run=False
    )


class TestConfigLoading:
    def test_loads_defaults_when_no_config(self, mirror):
        assert 'search_queries' in mirror.config
        assert 'clone_timeout_seconds' in mirror.config

    def test_loads_config_from_file(self, tmp_path):
        cfg = tmp_path / "test_config.json"
        cfg.write_text(json.dumps({"clone_timeout_seconds": 999}))
        m = OpenStaxMirror(
            mirror_dir=str(tmp_path / "mirror"),
            config_file=str(cfg)
        )
        assert m.config['clone_timeout_seconds'] == 999


class TestDiscovery:
    def test_fallback_discovery_from_md(self, tmp_path):
        """Fallback discovery should parse GitHub URLs from openstax_books.md."""
        md_content = """
## Books
- [Chemistry 2e](https://github.com/openstax/osbooks-chemistry-bundle)
- [Biology 2e](https://github.com/openstax/osbooks-biology-bundle)
"""
        md_file = tmp_path / "openstax_books.md"
        md_file.write_text(md_content)

        mirror = OpenStaxMirror(
            mirror_dir=str(tmp_path / "mirror"),
            config_file="nonexistent.json",
        )
        mirror.config['books_reference_file'] = str(md_file)
        mirror.config['http_request_timeout_seconds'] = 1

        # Mock requests.head to return 200
        with patch('get_books.requests.head') as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            result = mirror._fallback_discovery()

        assert result is True
        assert len(mirror.discovered_repos) == 2
        names = [r['name'] for r in mirror.discovered_repos]
        assert 'openstax/osbooks-chemistry-bundle' in names
        assert 'openstax/osbooks-biology-bundle' in names

    def test_github_api_discovery(self, tmp_mirror):
        """GitHub API discovery should add repos to discovered_repos."""
        mock_repo1 = MagicMock()
        mock_repo1.full_name = 'openstax/osbooks-chemistry-bundle'
        mock_repo1.clone_url = 'https://github.com/openstax/osbooks-chemistry-bundle.git'

        mock_gh = MagicMock()
        mock_gh.search_repositories.return_value = [mock_repo1]

        mirror = OpenStaxMirror(mirror_dir=str(tmp_mirror), config_file="nonexistent.json")
        mirror.gh = mock_gh

        mirror._find_via_github_api()
        assert len(mirror.discovered_repos) >= 1
        assert mirror.discovered_repos[0]['name'] == 'openstax/osbooks-chemistry-bundle'


class TestCloneAndUpdate:
    def test_clone_new_repo(self, tmp_mirror):
        """New repos should be cloned via git clone."""
        mirror = OpenStaxMirror(mirror_dir=str(tmp_mirror), config_file="nonexistent.json")
        mirror.discovered_repos = [
            {'name': 'openstax/test-repo', 'url': 'https://github.com/openstax/test-repo.git'}
        ]

        with patch('get_books.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            results = mirror.clone_or_update_repositories()

        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert 'git' in args and 'clone' in args
        assert len(results['failed']) == 0

    def test_update_existing_repo(self, tmp_mirror):
        """Existing repos (with .git dir) should be updated via git pull."""
        # Create a fake existing repo
        fake_repo = tmp_mirror / "openstax_test-repo"
        fake_repo.mkdir()
        (fake_repo / '.git').mkdir()

        mirror = OpenStaxMirror(mirror_dir=str(tmp_mirror), config_file="nonexistent.json")
        mirror.discovered_repos = [
            {'name': 'openstax/test-repo', 'url': 'https://github.com/openstax/test-repo.git'}
        ]

        with patch('get_books.subprocess.run') as mock_run:
            # First call: git rev-parse HEAD (before), second: git pull, third: rev-parse (after)
            mock_run.return_value = MagicMock(stdout='abc123\n', returncode=0)
            results = mirror.clone_or_update_repositories()

        # Should have called pull, not clone
        calls = [str(c) for c in mock_run.call_args_list]
        assert any('pull' in c for c in calls)

    def test_dry_run_skips_all(self, tmp_mirror):
        """Dry run should not execute any git commands."""
        mirror = OpenStaxMirror(mirror_dir=str(tmp_mirror), config_file="nonexistent.json",
                                dry_run=True)
        mirror.discovered_repos = [
            {'name': 'openstax/test-repo', 'url': 'https://github.com/openstax/test-repo.git'}
        ]

        with patch('get_books.subprocess.run') as mock_run:
            results = mirror.clone_or_update_repositories()

        # In dry run, git clone/pull should not be called
        # (git rev-parse may be called but not clone/pull)
        clone_calls = [c for c in mock_run.call_args_list
                       if 'clone' in str(c) or 'pull' in str(c)]
        assert len(clone_calls) == 0
        assert len(results['skipped']) == 1


class TestStats:
    def test_get_stats(self, tmp_mirror):
        """get_stats() should return correct count."""
        # Create some fake .git dirs
        for name in ['repo_a', 'repo_b']:
            fake_repo = tmp_mirror / name
            fake_repo.mkdir()
            (fake_repo / '.git').mkdir()

        mirror = OpenStaxMirror(mirror_dir=str(tmp_mirror), config_file="nonexistent.json")
        stats = mirror.get_stats()
        assert stats['repository_count'] == 2
        assert 'repo_a' in stats['repositories']
        assert 'repo_b' in stats['repositories']
