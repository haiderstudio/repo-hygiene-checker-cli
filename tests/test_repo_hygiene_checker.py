#!/usr/bin/env python3
"""Tests for repo_hygiene_checker. Run: python3 tests/test_repo_hygiene_checker.py

No third-party dependencies. The --online checks run against a real
local HTTP server started by the tests, never against the public
GitHub API.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from repo_hygiene_checker import check_github_meta, main, run_checks  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "repo_hygiene_checker.py"

MIT_TEXT = "MIT License\n\nCopyright (c) 2026 Haider Ali\n\nPermission is hereby granted.\n"
GOOD_README = """# sample-repo

A sample repo.

## Install

```sh
pip install sample
```

## Usage

```sh
sample --help
```

## Examples

See examples/.
"""
GOOD_GITIGNORE = "__pycache__/\n*.pyc\n.env\n"
GOOD_WORKFLOW = """name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 tests/test_sample.py
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_good_repo(base):
    """A repo that passes every offline check."""
    write(base / "README.md", GOOD_README)
    write(base / "LICENSE", MIT_TEXT)
    write(base / ".gitignore", GOOD_GITIGNORE)
    write(base / "CONTRIBUTING.md", "# Contributing\n")
    write(base / "SECURITY.md", "# Security\n")
    write(base / ".github" / "workflows" / "ci.yml", GOOD_WORKFLOW)
    write(base / ".github" / "ISSUE_TEMPLATE" / "bug_report.md", "---\nname: Bug\n---\n")
    write(base / "tests" / "test_sample.py", "def test_nothing():\n    assert True\n")
    write(base / "src" / "sample.py", "VALUE = 1\n")
    return base


def status_of(checks, check_id):
    for check in checks:
        if check.id == check_id:
            return check.status
    raise AssertionError(f"no check with id {check_id}")


class MetaHandler(BaseHTTPRequestHandler):
    """Serves one canned repo-meta response for --online tests."""

    meta = {"description": "A sample repo.", "topics": ["cli", "python"]}
    code = 200

    def do_GET(self):
        body = json.dumps(self.meta).encode("utf-8")
        self.send_response(self.code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_meta_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MetaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class TestGoodRepo(unittest.TestCase):
    def test_good_repo_passes_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            checks = run_checks(base, online=False)
            self.assertEqual([c.status for c in checks].count("FAIL"), 0)
            self.assertEqual(status_of(checks, "description"), "SKIP")
            self.assertEqual(status_of(checks, "topics"), "SKIP")
            self.assertEqual(main([str(base)]), 0)

    def test_good_repo_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            result = subprocess.run(
                [sys.executable, str(CLI), "--format", "json", str(base)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data["summary"]["failed"], 0)
            self.assertEqual(len(data["checks"]), 13)


class TestMissingFiles(unittest.TestCase):
    def test_missing_readme_fails_two_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            (base / "README.md").unlink()
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "readme"), "FAIL")
            self.assertEqual(status_of(checks, "readme-sections"), "FAIL")
            self.assertEqual(main([str(base)]), 1)

    def test_readme_without_usage_section_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(base / "README.md", "# sample-repo\n\n## Install\n\nx\n")
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "readme"), "PASS")
            self.assertEqual(status_of(checks, "readme-sections"), "FAIL")

    def test_singular_example_heading_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(
                base / "README.md",
                "# sample-repo\n\n## Install\n\nx\n\n## Usage\n\ny\n\n"
                "## Example\n\nz\n",
            )
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "readme-sections"), "PASS")

    def test_heading_inside_code_fence_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(
                base / "README.md",
                "# sample-repo\n\n## Install\n\nx\n\n## Example\n\nz\n\n"
                "```sh\n# Usage\nsample --help\n```\n",
            )
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "readme-sections"), "FAIL")

    def test_licence_file_without_mit_text_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(base / "LICENSE", "Apache License\nVersion 2.0\n")
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "license"), "FAIL")

    def test_missing_gitignore_fails_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            (base / ".gitignore").unlink()
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "gitignore"), "FAIL")
            self.assertEqual(status_of(checks, "gitignore-coverage"), "FAIL")

    def test_gitignore_without_pycache_fails_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(base / ".gitignore", ".env\n")
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "gitignore"), "PASS")
            self.assertEqual(status_of(checks, "gitignore-coverage"), "FAIL")

    def test_workflow_without_test_step_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(
                base / ".github" / "workflows" / "ci.yml",
                "name: CI\non: [push]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: echo hi\n",
            )
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "ci-runs-tests"), "FAIL")

    def test_no_issue_templates_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            (base / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").unlink()
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "issue-templates"), "FAIL")


class TestWarnings(unittest.TestCase):
    def test_missing_contributing_warns_but_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            (base / "CONTRIBUTING.md").unlink()
            (base / "SECURITY.md").unlink()
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "contributing"), "WARN")
            self.assertEqual(status_of(checks, "security"), "WARN")
            self.assertEqual(main([str(base)]), 0)

    def test_strict_turns_warnings_into_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            (base / "CONTRIBUTING.md").unlink()
            self.assertEqual(main(["--strict", str(base)]), 1)

    def test_skill_frontmatter_checked_when_skills_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            write(
                base / "skills" / "my-skill" / "SKILL.md",
                "# My skill\n\nNo frontmatter here.\n",
            )
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "skill-frontmatter"), "WARN")
            write(
                base / "skills" / "my-skill" / "SKILL.md",
                "---\nname: my-skill\ndescription: Does one job.\n---\n\n# My skill\n",
            )
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "skill-frontmatter"), "PASS")

    def test_no_skills_dir_skips_frontmatter_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            checks = run_checks(base, online=False)
            self.assertEqual(status_of(checks, "skill-frontmatter"), "SKIP")


class TestOnlineChecks(unittest.TestCase):
    def _repo_with_remote(self, tmp):
        base = make_good_repo(Path(tmp))
        write(
            base / ".git" / "config",
            '[remote "origin"]\n\turl = https://github.com/example/sample-repo.git\n',
        )
        return base

    def test_online_passes_with_description_and_topics(self):
        server = start_meta_server()
        try:
            MetaHandler.meta = {"description": "A sample repo.", "topics": ["cli"]}
            MetaHandler.code = 200
            with tempfile.TemporaryDirectory() as tmp:
                base = self._repo_with_remote(tmp)
                os.environ["REPO_HYGIENE_API_BASE"] = (
                    f"http://127.0.0.1:{server.server_address[1]}"
                )
                try:
                    checks = check_github_meta(base, online=True)
                finally:
                    del os.environ["REPO_HYGIENE_API_BASE"]
                self.assertEqual(status_of(checks, "description"), "PASS")
                self.assertEqual(status_of(checks, "topics"), "PASS")
        finally:
            server.shutdown()
            server.server_close()

    def test_online_fails_on_empty_description(self):
        server = start_meta_server()
        try:
            MetaHandler.meta = {"description": "", "topics": []}
            MetaHandler.code = 200
            with tempfile.TemporaryDirectory() as tmp:
                base = self._repo_with_remote(tmp)
                os.environ["REPO_HYGIENE_API_BASE"] = (
                    f"http://127.0.0.1:{server.server_address[1]}"
                )
                try:
                    checks = check_github_meta(base, online=True)
                finally:
                    del os.environ["REPO_HYGIENE_API_BASE"]
                self.assertEqual(status_of(checks, "description"), "FAIL")
                self.assertEqual(status_of(checks, "topics"), "FAIL")
        finally:
            server.shutdown()
            server.server_close()

    def test_online_without_remote_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_good_repo(Path(tmp))
            checks = check_github_meta(base, online=True)
            self.assertEqual(status_of(checks, "description"), "SKIP")
            self.assertEqual(status_of(checks, "topics"), "SKIP")


class TestUsageErrors(unittest.TestCase):
    def test_missing_path_exits_two(self):
        self.assertEqual(main(["/definitely/not/a/real/path"]), 2)

    def test_file_not_directory_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "file.txt"
            target.write_text("hi", encoding="utf-8")
            self.assertEqual(main([str(target)]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
