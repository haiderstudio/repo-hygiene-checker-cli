#!/usr/bin/env python3
"""Check a repo is publish-ready against a fixed publish template.

Usage:
    python3 src/repo_hygiene_checker.py [PATH]
    python3 src/repo_hygiene_checker.py --online [PATH]
    python3 src/repo_hygiene_checker.py --format json [PATH]
    python3 src/repo_hygiene_checker.py --strict [PATH]

PATH defaults to the current directory. The tool only reads the repo;
it never writes, deletes, or sends anything anywhere, except for one
optional network call: with --online it asks the public GitHub API
for the repo's description and topics (no token, no login). Without
--online those two checks report SKIPPED, never PASS.

Every check is PASS, FAIL, WARN, or SKIP. A check is never reported
PASS unless its test actually ran. Exit code 0 means no FAIL (warnings
allowed), 1 means at least one FAIL (or a WARN with --strict), 2 means
a usage error such as a missing path.

What makes this different from a generic file-presence checker: it
checks conformance to a publish template, not just that files exist.
The README must carry Install, Usage, and Examples sections; the
licence file must actually contain MIT licence text; .gitignore must
actually cover the junk it claims to; the CI workflow must contain a
step that runs tests; and agent-skill repos get their SKILL.md
frontmatter checked too.

Python standard library only.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0.0"

README_NAMES = ("README.md", "README", "README.rst", "README.txt")
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
REMOTE_RE = re.compile(
    r"github\.com[/:](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?\s*$",
    re.MULTILINE,
)
TEST_STEP_RE = re.compile(
    r"pytest|unittest|python3?\s+tests/|python3?\s+-m\s+(pytest|unittest)"
)
# Test-only seam: tests point this at a local HTTP server by setting
# REPO_HYGIENE_API_BASE. Not a user-facing option; the default is the
# public GitHub API. Read at call time so tests can set it per run.
def _api_base():
    return os.environ.get("REPO_HYGIENE_API_BASE", "https://api.github.com")


class Check:
    """One check result. status is PASS, FAIL, WARN, or SKIP."""

    def __init__(self, check_id, name, status, detail):
        self.id = check_id
        self.name = name
        self.status = status
        self.detail = detail

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _first_existing(root, names):
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


FENCE_RE = re.compile(r"^```.*?$.*?^```", re.MULTILINE | re.DOTALL)
TILDE_FENCE_RE = re.compile(r"^~~~.*?$.*?^~~~", re.MULTILINE | re.DOTALL)


def _strip_fences(text):
    """Remove fenced code blocks so a heading inside a code sample
    never counts as a real section heading."""
    text = FENCE_RE.sub("", text)
    return TILDE_FENCE_RE.sub("", text)


def _headings(text):
    return [
        match.group(1).strip().lower()
        for match in HEADING_RE.finditer(_strip_fences(text))
    ]


def check_readme(root):
    readme = _first_existing(root, README_NAMES)
    if readme is None:
        return Check("readme", "README", "FAIL", "no README file found")
    text = _read(readme)
    if text is None or not text.strip():
        return Check("readme", "README", "FAIL", f"{readme.name} is empty")
    if not re.search(r"^#\s+\S", _strip_fences(text), re.MULTILINE):
        return Check(
            "readme", "README", "FAIL", f"{readme.name} has no top-level heading"
        )
    return Check(
        "readme", "README", "PASS", f"{readme.name} present, non-empty, has heading"
    )


def check_readme_sections(root):
    readme = _first_existing(root, README_NAMES)
    if readme is None:
        return Check(
            "readme-sections", "README sections", "FAIL", "no README file found"
        )
    text = _read(readme) or ""
    headings = _headings(text)
    # "Example" (singular) counts, as does "Installation" / "Use".
    wanted = ("install", "usage", "example")
    missing = [
        section
        for section in wanted
        if not any(heading.startswith(section) for heading in headings)
    ]
    if missing:
        return Check(
            "readme-sections",
            "README sections",
            "FAIL",
            "missing section(s): " + ", ".join(missing),
        )
    return Check(
        "readme-sections",
        "README sections",
        "PASS",
        "Install, Usage, and Examples sections present",
    )


def check_license(root):
    licence = _first_existing(root, LICENSE_NAMES)
    if licence is None:
        return Check("license", "Licence (MIT)", "FAIL", "no licence file found")
    text = _read(licence)
    if text is None or not text.strip():
        return Check("license", "Licence (MIT)", "FAIL", f"{licence.name} is empty")
    if "mit license" not in text.lower():
        return Check(
            "license",
            "Licence (MIT)",
            "FAIL",
            f"{licence.name} exists but does not contain MIT licence text",
        )
    return Check(
        "license", "Licence (MIT)", "PASS", f"{licence.name} contains MIT licence text"
    )


def check_gitignore(root):
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return Check("gitignore", ".gitignore", "FAIL", ".gitignore not found")
    text = _read(gitignore)
    if text is None or not text.strip():
        return Check("gitignore", ".gitignore", "FAIL", ".gitignore is empty")
    return Check("gitignore", ".gitignore", "PASS", ".gitignore present, non-empty")


def _gitignore_patterns(root):
    gitignore = root / ".gitignore"
    text = _read(gitignore)
    if text is None:
        return set()
    patterns = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def check_gitignore_coverage(root):
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return Check(
            "gitignore-coverage",
            ".gitignore coverage",
            "FAIL",
            ".gitignore not found",
        )
    patterns = _gitignore_patterns(root)
    has_python = any(root.rglob("*.py"))
    missing = []
    if has_python and not (
        "__pycache__/" in patterns
        or "__pycache__" in patterns
        or "*.pyc" in patterns
    ):
        missing.append("__pycache__/ or *.pyc")
    if ".env" not in patterns:
        missing.append(".env")
    if missing:
        return Check(
            "gitignore-coverage",
            ".gitignore coverage",
            "FAIL",
            ".gitignore does not cover: " + ", ".join(missing),
        )
    if not has_python:
        return Check(
            "gitignore-coverage",
            ".gitignore coverage",
            "PASS",
            ".env covered (no Python files, so no cache pattern needed)",
        )
    return Check(
        "gitignore-coverage",
        ".gitignore coverage",
        "PASS",
        ".env and Python cache patterns covered",
    )


def check_ci_runs_tests(root):
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return Check(
            "ci-runs-tests", "CI runs tests", "FAIL", ".github/workflows/ not found"
        )
    workflows = sorted(
        [p for p in workflows_dir.iterdir() if p.suffix in (".yml", ".yaml")]
    )
    if not workflows:
        return Check(
            "ci-runs-tests",
            "CI runs tests",
            "FAIL",
            "no workflow file in .github/workflows/",
        )
    for workflow in workflows:
        text = _read(workflow)
        if text and text.strip() and TEST_STEP_RE.search(text):
            return Check(
                "ci-runs-tests",
                "CI runs tests",
                "PASS",
                f"{workflow.name} contains a step that runs tests",
            )
    return Check(
        "ci-runs-tests",
        "CI runs tests",
        "FAIL",
        "workflow file(s) exist but no step runs tests",
    )


def check_issue_templates(root):
    templates_dir = root / ".github" / "ISSUE_TEMPLATE"
    single_file = root / ".github" / "ISSUE_TEMPLATE.yml"
    single_file_yaml = root / ".github" / "ISSUE_TEMPLATE.yaml"
    if single_file.is_file() or single_file_yaml.is_file():
        return Check(
            "issue-templates",
            "Issue templates",
            "PASS",
            ".github/ISSUE_TEMPLATE.yml present",
        )
    if templates_dir.is_dir():
        templates = sorted(
            [
                p
                for p in templates_dir.iterdir()
                if p.is_file() and p.suffix in (".md", ".yml", ".yaml")
            ]
        )
        if templates:
            return Check(
                "issue-templates",
                "Issue templates",
                "PASS",
                f"{len(templates)} template(s) in .github/ISSUE_TEMPLATE/",
            )
    return Check(
        "issue-templates",
        "Issue templates",
        "FAIL",
        "no issue template in .github/ISSUE_TEMPLATE/",
    )


def check_contributing(root):
    if (root / "CONTRIBUTING.md").is_file():
        return Check(
            "contributing", "CONTRIBUTING.md", "PASS", "CONTRIBUTING.md present"
        )
    return Check(
        "contributing",
        "CONTRIBUTING.md",
        "WARN",
        "CONTRIBUTING.md missing (recommended, not blocking)",
    )


def check_security(root):
    if (root / "SECURITY.md").is_file():
        return Check("security", "SECURITY.md", "PASS", "SECURITY.md present")
    return Check(
        "security",
        "SECURITY.md",
        "WARN",
        "SECURITY.md missing (recommended, not blocking)",
    )


def check_skill_frontmatter(root):
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return Check(
            "skill-frontmatter",
            "Skill frontmatter",
            "SKIP",
            "no skills/ directory",
        )
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        return Check(
            "skill-frontmatter",
            "Skill frontmatter",
            "SKIP",
            "no SKILL.md files under skills/",
        )
    bad = []
    for skill_file in skill_files:
        text = _read(skill_file) or ""
        match = FRONTMATTER_RE.match(text)
        frontmatter = match.group(1) if match else ""
        has_name = re.search(r"^name:\s*\S+", frontmatter, re.MULTILINE) is not None
        has_description = (
            re.search(r"^description:\s*\S+", frontmatter, re.MULTILINE) is not None
        )
        if not (has_name and has_description):
            bad.append(skill_file.parent.name)
    if bad:
        return Check(
            "skill-frontmatter",
            "Skill frontmatter",
            "WARN",
            "SKILL.md missing name/description frontmatter: " + ", ".join(bad),
        )
    return Check(
        "skill-frontmatter",
        "Skill frontmatter",
        "PASS",
        f"{len(skill_files)} SKILL.md file(s) with name + description frontmatter",
    )


def check_tests_present(root):
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        test_files = [
            p
            for p in tests_dir.iterdir()
            if p.is_file()
            and (p.name.startswith("test_") or p.name.endswith("_test.py"))
        ]
        if test_files:
            return Check(
                "tests-present",
                "Tests present",
                "PASS",
                f"{len(test_files)} test file(s) in tests/",
            )
    return Check(
        "tests-present",
        "Tests present",
        "WARN",
        "no test files in tests/ (recommended, not blocking)",
    )


def _github_repo(root):
    config = root / ".git" / "config"
    text = _read(config)
    if text is None:
        return None
    match = REMOTE_RE.search(text)
    if match is None:
        return None
    return match.group("owner"), match.group("repo")


def _fetch_repo_meta(owner, repo):
    url = f"{_api_base()}/repos/{owner}/{repo}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "repo-hygiene-checker-cli", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def check_github_meta(root, online):
    """Description + topics. Offline, or without a GitHub remote, both SKIP."""
    if not online:
        return [
            Check(
                "description",
                "GitHub description",
                "SKIP",
                "needs --online (no network call made)",
            ),
            Check(
                "topics",
                "GitHub topics",
                "SKIP",
                "needs --online (no network call made)",
            ),
        ]
    repo = _github_repo(root)
    if repo is None:
        return [
            Check(
                "description",
                "GitHub description",
                "SKIP",
                "no GitHub remote found in .git/config",
            ),
            Check(
                "topics", "GitHub topics", "SKIP", "no GitHub remote found in .git/config"
            ),
        ]
    owner, name = repo
    try:
        meta = _fetch_repo_meta(owner, name)
    except urllib.error.HTTPError as exc:
        reason = f"GitHub API answered HTTP {exc.code} for {owner}/{name}"
        return [
            Check("description", "GitHub description", "SKIP", reason),
            Check("topics", "GitHub topics", "SKIP", reason),
        ]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = f"GitHub API unreachable ({exc})"
        return [
            Check("description", "GitHub description", "SKIP", reason),
            Check("topics", "GitHub topics", "SKIP", reason),
        ]
    description = meta.get("description") or ""
    topics = meta.get("topics") or []
    return [
        Check(
            "description",
            "GitHub description",
            "PASS" if description.strip() else "FAIL",
            f"description is {description.strip()!r}" if description.strip()
            else "description is empty on GitHub",
        ),
        Check(
            "topics",
            "GitHub topics",
            "PASS" if topics else "FAIL",
            f"{len(topics)} topic(s): " + ", ".join(topics) if topics
            else "no topics set on GitHub",
        ),
    ]


def run_checks(root, online):
    checks = [
        check_readme(root),
        check_readme_sections(root),
        check_license(root),
        check_gitignore(root),
        check_gitignore_coverage(root),
        check_ci_runs_tests(root),
        check_issue_templates(root),
        check_contributing(root),
        check_security(root),
        check_skill_frontmatter(root),
        check_tests_present(root),
    ]
    checks.extend(check_github_meta(root, online))
    return checks


def summarize(checks, strict):
    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    warned = sum(1 for c in checks if c.status == "WARN")
    skipped = sum(1 for c in checks if c.status == "SKIP")
    if strict:
        failed += warned
        warned = 0
    return {
        "passed": passed,
        "failed": failed,
        "warnings": warned,
        "skipped": skipped,
    }


def format_text(root, checks, summary):
    lines = [f"repo-hygiene-checker: {root}"]
    for check in checks:
        lines.append(f"{check.status:4}  {check.name}: {check.detail}")
    lines.append(
        "repo-hygiene-checker: "
        f"{summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['warnings']} warnings, {summary['skipped']} skipped"
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check a repo is publish-ready against a fixed publish template."
    )
    parser.add_argument("path", nargs="?", default=".", help="repo to check")
    parser.add_argument(
        "--online",
        action="store_true",
        help="also check GitHub description and topics via the public API",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="warnings count as failures",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        print(f"repo-hygiene-checker: {args.path}: no such directory", file=sys.stderr)
        return 2

    checks = run_checks(root, args.online)
    summary = summarize(checks, args.strict)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "path": str(root),
                    "checks": [c.as_dict() for c in checks],
                    "summary": summary,
                },
                indent=2,
            )
        )
    else:
        print(format_text(root, checks, summary))

    if summary["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
