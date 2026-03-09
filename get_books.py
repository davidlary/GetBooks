"""
GetBooks - OpenStax Mirror Manager

Maintains an up-to-date local mirror of all OpenStax CNXML repositories.
Strips all curriculum/standards logic from Books/GetBooks.py - pure mirror management only.

Usage:
    python get_books.py                      # Full mirror update
    python get_books.py --check-updates      # Non-destructive status report
    python get_books.py --dry-run            # Preview only
    python get_books.py --stats              # Show statistics
    python get_books.py --verbose            # Debug logging
"""

import os
import json
import subprocess
import logging
import shutil
import argparse
import requests
import re
from datetime import datetime

try:
    from github import Github
    from github.GithubException import GithubException
    PYGITHUB_AVAILABLE = True
except ImportError:
    PYGITHUB_AVAILABLE = False


DEFAULT_CONFIG = {
    "search_queries": {
        "openstax_main": "org:openstax osbooks- in:name",
        "cnx_books": "org:cnx-user-books cnxbook in:name",
        "additional_orgs": []
    },
    "books_reference_file": "openstax_books.md",
    "clone_timeout_seconds": 300,
    "http_request_timeout_seconds": 10,
}


class OpenStaxMirror:
    """
    Auto-discovers and mirrors OpenStax CNXML Git repositories.
    Pure mirror management — no curriculum or standards processing.
    """

    def __init__(self, github_token=None, mirror_dir="openstax_mirror",
                 config_file="openstax_config.json", dry_run=False,
                 log_level=logging.INFO):
        self.github_token = github_token
        self.mirror_dir = mirror_dir
        self.config_file = config_file
        self.dry_run = dry_run

        self._setup_logging(log_level)
        self._validate_dependencies()
        self.config = self._load_config()

        if github_token and PYGITHUB_AVAILABLE:
            try:
                from github import Auth as GithubAuth
                self.gh = Github(auth=GithubAuth.Token(github_token))
            except (ImportError, TypeError):
                # Older PyGithub versions use positional token arg
                self.gh = Github(github_token)
        else:
            self.gh = None

        self.discovered_repos = []
        self.state_file = os.path.join(self.mirror_dir, '.getbooks_state.json')
        self.last_state = self._load_state()
        self._whitelist = self._load_whitelist()  # repo paths from openstax_books.md

    def _setup_logging(self, log_level):
        os.makedirs("logs", exist_ok=True)
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/get_books.log')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def _validate_dependencies(self):
        self.logger = logging.getLogger(__name__)
        try:
            subprocess.run(['git', '--version'], capture_output=True, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise SystemExit("Git is required but not found.")
        if not PYGITHUB_AVAILABLE:
            self.logger.warning("PyGithub not installed — GitHub API discovery disabled; falling back to openstax_books.md")

    def _load_config(self):
        config = DEFAULT_CONFIG.copy()
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                config.update(loaded)
                self.logger.info(f"Loaded config from {self.config_file}")
            except Exception as e:
                self.logger.warning(f"Could not load {self.config_file}: {e} — using defaults")
        return config

    def _load_whitelist(self) -> set:
        """Load the set of allowed repo paths (org/repo) from openstax_books.md."""
        md_file = self.config.get("books_reference_file", "openstax_books.md")
        if not os.path.exists(md_file):
            self.logger.warning(f"Whitelist file {md_file} not found — all repos will be accepted")
            return set()
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            paths = set()
            for path in re.findall(r'https://github\.com/([^)\]\s]+)', content):
                path = path.rstrip('/')
                if '.' not in path.split('/')[-1]:  # skip file links
                    paths.add(path.lower())
            self.logger.info(f"Whitelist loaded: {len(paths)} repos from {md_file}")
            return paths
        except Exception as e:
            self.logger.warning(f"Could not load whitelist: {e}")
            return set()

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                self.logger.info(f"Loaded state: {len(state.get('repositories', {}))} repos tracked")
                return state
        except Exception as e:
            self.logger.warning(f"Could not load state: {e}")
        return {'repositories': {}, 'last_run': None}

    def _save_state(self):
        state = {
            'repositories': {},
            'last_run': datetime.now().isoformat(),
            'total_repositories': len(self.discovered_repos)
        }
        for repo_info in self.discovered_repos:
            repo_name = repo_info['name']
            local_path = repo_info.get('local_path', '')
            repo_state = {
                'url': repo_info['url'],
                'local_path': local_path,
                'last_analyzed': datetime.now().isoformat(),
            }
            if local_path and os.path.exists(local_path):
                try:
                    result = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                           cwd=local_path, capture_output=True, text=True, check=True)
                    repo_state['commit_hash'] = result.stdout.strip()
                except Exception:
                    pass
            state['repositories'][repo_name] = repo_state

        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Could not save state: {e}")

    def _get_commit_hash(self, local_path):
        try:
            result = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                   cwd=local_path, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception:
            return None

    def find_repositories(self):
        """Discover all OpenStax repositories via GitHub API or fallback."""
        if self.gh is not None:
            return self._find_via_github_api()
        return self._fallback_discovery()

    def _find_via_github_api(self):
        self.logger.info("Searching for OpenStax repositories via GitHub API...")
        try:
            for query_key, query in self.config["search_queries"].items():
                if query_key == "additional_orgs":
                    for org_query in query:
                        self._search_github(org_query)
                else:
                    self._search_github(query)
            self.logger.info(f"Found {len(self.discovered_repos)} repositories via GitHub API")
            return True
        except Exception as e:
            self.logger.warning(f"GitHub API search failed: {e} — falling back to openstax_books.md")
            return self._fallback_discovery()

    def _search_github(self, query):
        try:
            repos = self.gh.search_repositories(query)
            for repo in repos:
                full_name = repo.full_name
                # Enforce whitelist: only clone repos listed in openstax_books.md
                if self._whitelist and full_name.lower() not in self._whitelist:
                    self.logger.debug(f"  Skipping (not in whitelist): {full_name}")
                    continue
                if not any(r['name'] == full_name for r in self.discovered_repos):
                    self.discovered_repos.append({
                        'name': full_name,
                        'url': repo.clone_url
                    })
                    self.logger.debug(f"  Found: {full_name}")
        except Exception as e:
            if hasattr(e, 'status') and e.status == 403:
                self.logger.warning(f"Rate limit hit for query '{query}'")
                raise
            self.logger.warning(f"Search failed for '{query}': {e}")

    def _fallback_discovery(self):
        """Discover repos from openstax_books.md GitHub URLs."""
        self.logger.info("Fallback: discovering repos from openstax_books.md...")
        md_file = self.config.get("books_reference_file", "openstax_books.md")
        if not os.path.exists(md_file):
            self.logger.error(f"{md_file} not found")
            return False
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            github_paths = re.findall(r'https://github\.com/([^)\]\s]+)', content)
            seen = set()
            timeout = self.config.get("http_request_timeout_seconds", 10)
            for path in github_paths:
                path = path.rstrip('/')
                if path in seen or '.' in path.split('/')[-1]:
                    continue
                seen.add(path)
                url = f'https://github.com/{path}'
                try:
                    resp = requests.head(url, timeout=timeout)
                    if resp.status_code == 200:
                        self.discovered_repos.append({'name': path, 'url': url})
                        self.logger.debug(f"  Found: {path}")
                except Exception:
                    pass
            self.logger.info(f"Fallback found {len(self.discovered_repos)} repositories")
            return True
        except Exception as e:
            self.logger.error(f"Fallback discovery error: {e}")
            return False

    def clone_or_update_repositories(self):
        """Clone new repos, pull updates for existing ones."""
        os.makedirs(self.mirror_dir, exist_ok=True)
        results = {'cloned': [], 'updated': [], 'skipped': [], 'failed': []}
        total = len(self.discovered_repos)

        for idx, repo_info in enumerate(self.discovered_repos, 1):
            repo_name = repo_info['name']
            repo_url = repo_info['url']
            local_name = repo_name.replace('/', '_')
            local_path = os.path.join(self.mirror_dir, local_name)
            repo_info['local_path'] = local_path

            prefix = f"  [{idx}/{total}]"

            if os.path.exists(os.path.join(local_path, '.git')):
                # Existing repo — check if update needed
                current_hash = self._get_commit_hash(local_path)
                if self.dry_run:
                    self.logger.info(f"{prefix} [DRY RUN] Would pull: {repo_name}")
                    results['skipped'].append(repo_name)
                    continue
                try:
                    subprocess.run(['git', 'pull', '--ff-only'], cwd=local_path,
                                   capture_output=True, text=True, check=True,
                                   timeout=self.config.get("clone_timeout_seconds", 300))
                    new_hash = self._get_commit_hash(local_path)
                    if new_hash != current_hash:
                        self.logger.info(f"{prefix} Updated: {repo_name}")
                        results['updated'].append(repo_name)
                    else:
                        self.logger.debug(f"{prefix} Up to date: {repo_name}")
                        results['skipped'].append(repo_name)
                except subprocess.CalledProcessError as e:
                    self.logger.warning(f"{prefix} Pull failed for {repo_name}: {e.stderr.strip()}")
                    results['failed'].append(repo_name)
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"{prefix} Pull timed out: {repo_name}")
                    results['failed'].append(repo_name)
            else:
                # New repo — clone it
                if os.path.exists(local_path):
                    shutil.rmtree(local_path)
                if self.dry_run:
                    self.logger.info(f"{prefix} [DRY RUN] Would clone: {repo_name}")
                    results['skipped'].append(repo_name)
                    continue
                self.logger.info(f"{prefix} Cloning {repo_name}...")
                try:
                    timeout = self.config.get("clone_timeout_seconds", 300)
                    subprocess.run(['git', 'clone', repo_url, local_path],
                                   capture_output=True, text=True, check=True, timeout=timeout)
                    self.logger.info(f"{prefix} Cloned: {repo_name}")
                    results['cloned'].append(repo_name)
                except subprocess.TimeoutExpired:
                    self.logger.error(f"{prefix} Clone timed out: {repo_name}")
                    results['failed'].append(repo_name)
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"{prefix} Clone failed: {repo_name} — {e.stderr.strip()}")
                    results['failed'].append(repo_name)

        return results

    def check_updates(self):
        """Non-destructive check: which repos have upstream changes."""
        self.logger.info("Checking for upstream updates (non-destructive)...")
        status = []
        for repo_name, repo_state in self.last_state.get('repositories', {}).items():
            local_path = repo_state.get('local_path', '')
            if not os.path.exists(os.path.join(local_path, '.git')):
                status.append({'repo': repo_name, 'status': 'missing'})
                continue
            try:
                subprocess.run(['git', 'fetch', '--dry-run'], cwd=local_path,
                               capture_output=True, text=True, check=True, timeout=30)
                result = subprocess.run(['git', 'status', '-uno'],
                                        cwd=local_path, capture_output=True, text=True)
                if 'behind' in result.stdout:
                    status.append({'repo': repo_name, 'status': 'behind'})
                else:
                    status.append({'repo': repo_name, 'status': 'current'})
            except Exception as e:
                status.append({'repo': repo_name, 'status': f'error: {e}'})
        return status

    def pull_existing_mirror(self):
        """
        Pull latest commits for all repos already present in mirror_dir.
        Does not require GitHub API — works purely via git pull on local clones.
        Used when discovery is not needed (repos already cloned).
        """
        results = {'updated': [], 'skipped': [], 'failed': []}
        if not os.path.exists(self.mirror_dir):
            self.logger.error(f"Mirror directory not found: {self.mirror_dir}")
            return results

        repos = [
            d for d in os.scandir(self.mirror_dir)
            if d.is_dir() and os.path.exists(os.path.join(d.path, '.git'))
        ]
        total = len(repos)
        self.logger.info(f"Pulling updates for {total} repos in {self.mirror_dir}...")

        timeout = self.config.get("clone_timeout_seconds", 300)
        for idx, entry in enumerate(sorted(repos, key=lambda e: e.name), 1):
            local_path = entry.path
            repo_name = entry.name
            prefix = f"  [{idx}/{total}]"
            before_hash = self._get_commit_hash(local_path)
            try:
                subprocess.run(
                    ['git', 'pull', '--ff-only'],
                    cwd=local_path, capture_output=True, text=True,
                    check=True, timeout=timeout
                )
                after_hash = self._get_commit_hash(local_path)
                if after_hash != before_hash:
                    self.logger.info(f"{prefix} Updated: {repo_name}")
                    results['updated'].append(repo_name)
                else:
                    self.logger.info(f"{prefix} Already current: {repo_name}")
                    results['skipped'].append(repo_name)
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"{prefix} Pull failed for {repo_name}: {e.stderr.strip()}")
                results['failed'].append(repo_name)
            except subprocess.TimeoutExpired:
                self.logger.warning(f"{prefix} Pull timed out: {repo_name}")
                results['failed'].append(repo_name)

        self.logger.info(
            f"Pull complete: {len(results['updated'])} updated, "
            f"{len(results['skipped'])} already current, "
            f"{len(results['failed'])} failed"
        )
        return results

    def get_stats(self):
        """Return statistics about the current mirror."""
        repos = []
        if os.path.exists(self.mirror_dir):
            for entry in os.scandir(self.mirror_dir):
                if entry.is_dir() and os.path.exists(os.path.join(entry.path, '.git')):
                    repos.append(entry.name)
        return {
            'mirror_dir': self.mirror_dir,
            'repository_count': len(repos),
            'repositories': sorted(repos),
            'last_run': self.last_state.get('last_run')
        }

    def update_mirror(self):
        """Full mirror update: discover -> clone/pull -> save state."""
        self.logger.info("Starting full mirror update...")
        self.find_repositories()
        results = self.clone_or_update_repositories()
        self._save_state()
        self.logger.info(
            f"Mirror update complete: "
            f"{len(results['cloned'])} cloned, "
            f"{len(results['updated'])} updated, "
            f"{len(results['skipped'])} already current, "
            f"{len(results['failed'])} failed"
        )
        return results


def main():
    parser = argparse.ArgumentParser(description="OpenStax Mirror Manager")
    parser.add_argument('--mirror-dir', default='openstax_mirror', help='Mirror directory')
    parser.add_argument('--config', default='openstax_config.json', help='Config file')
    parser.add_argument('--token', default=os.environ.get('GITHUB_TOKEN'), help='GitHub token')
    parser.add_argument('--dry-run', action='store_true', help='Preview without changes')
    parser.add_argument('--check-updates', action='store_true', help='Non-destructive update check')
    parser.add_argument('--pull-existing', action='store_true',
                        help='Pull latest for all already-cloned repos (no API needed)')
    parser.add_argument('--stats', action='store_true', help='Show mirror statistics')
    parser.add_argument('--verbose', action='store_true', help='Debug logging')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    mirror = OpenStaxMirror(
        github_token=args.token,
        mirror_dir=args.mirror_dir,
        config_file=args.config,
        dry_run=args.dry_run,
        log_level=log_level
    )

    if args.stats:
        stats = mirror.get_stats()
        print(json.dumps(stats, indent=2))
    elif args.check_updates:
        status = mirror.check_updates()
        for s in status:
            print(f"  {s['status']:10s}  {s['repo']}")
    elif args.pull_existing:
        mirror.pull_existing_mirror()
    else:
        mirror.update_mirror()


if __name__ == '__main__':
    main()
