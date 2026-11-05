# repo-hygiene-checker-cli

Check a repo is publish-ready against a fixed publish template — pass/fail per check, nothing invented.

[![CI](https://github.com/haiderstudio/repo-hygiene-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/repo-hygiene-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`repo-hygiene-checker` reads a repo and reports, for each check, one of `PASS`, `FAIL`, `WARN`, or `SKIP`. A check is never reported PASS unless its test actually ran. Exit code 0 means no failures (warnings allowed), 1 means at least one failure, 2 means a usage error such as a missing path.

Required checks (a missing one is a FAIL):

- README exists, is non-empty, and has a top-level heading.
- README carries Install, Usage, and Examples sections.
- A licence file exists and actually contains MIT licence text — a file named LICENSE with other text fails.
- `.gitignore` exists and is non-empty, and actually covers `.env` plus Python cache files (`__pycache__/` or `*.pyc`) when the repo contains Python files.
- A CI workflow exists in `.github/workflows/` and contains a step that runs tests — a workflow with no test step fails.
- At least one issue template exists in `.github/ISSUE_TEMPLATE/`.
- With `--online` only: the GitHub description is non-empty and at least one topic is set (read from the public GitHub API, no token). Without `--online` both report SKIP, never PASS.

Recommended checks (a missing one is a WARN, not a FAIL; `--strict` turns warnings into failures):

- CONTRIBUTING.md and SECURITY.md present.
- If the repo has a `skills/` directory, every `skills/*/SKILL.md` carries `name:` and `description:` frontmatter.
- A `tests/` directory with at least one test file.

## What it does NOT do

- It does not fix anything. It only reads and reports — no file is ever written, deleted, or renamed.
- It does not guess. A check that cannot run (offline description/topics, no `skills/` directory) reports SKIP with the reason, never PASS.
- It does not check README quality, spelling, or code correctness — only that the publish template is present and conformed to.
- It does not send your code anywhere. Without `--online` it makes no network call at all; with `--online` its only call is one unauthenticated read of the public GitHub API for the checked repo's description and topics.

## Who it is for

Anyone about to publish a small open-source repo — especially an agent skill or a small CLI — who wants a one-command gate that catches the missing file before a reader does, in CI or as a one-off check before publishing.

## How this differs from similar tools

Generic presence checkers already exist: `repogap` checks README / LICENSE / `.gitignore` / CHANGELOG presence plus `package.json` / `pyproject.toml` fields, and `repo-doctor` scores 17 rules and auto-generates missing files. This tool does a different, narrower job: it checks conformance to a publish template — README section order, MIT licence *text* (not just a file with the right name), `.gitignore` *content*, a CI workflow that actually runs tests, and SKILL.md frontmatter. It never writes anything, and it never calls a check PASS that did not run.

## Install

Python standard library only — no packages to download. Clone the repo and run it in place:

```sh
git clone https://github.com/haiderstudio/repo-hygiene-checker-cli.git
cd repo-hygiene-checker-cli
```

## Usage

Check a repo (defaults to the current directory):

```sh
python3 src/repo_hygiene_checker.py examples/good-repo
python3 src/repo_hygiene_checker.py /path/to/your-repo
```

Real output from the bundled examples:

```text
repo-hygiene-checker: examples/good-repo
PASS  README: README.md present, non-empty, has heading
PASS  README sections: Install, Usage, and Examples sections present
PASS  Licence (MIT): LICENSE contains MIT licence text
PASS  .gitignore: .gitignore present, non-empty
PASS  .gitignore coverage: .env and Python cache patterns covered
PASS  CI runs tests: ci.yml contains a step that runs tests
PASS  Issue templates: 1 template(s) in .github/ISSUE_TEMPLATE/
PASS  CONTRIBUTING.md: CONTRIBUTING.md present
PASS  SECURITY.md: SECURITY.md present
SKIP  Skill frontmatter: no skills/ directory
PASS  Tests present: 1 test file(s) in tests/
SKIP  GitHub description: needs --online (no network call made)
SKIP  GitHub topics: needs --online (no network call made)
repo-hygiene-checker: 10 passed, 0 failed, 0 warnings, 3 skipped
```

Useful flags:

```sh
# Also check the GitHub description and topics (one public API read, no token)
python3 src/repo_hygiene_checker.py --online /path/to/your-repo

# Machine-readable output
python3 src/repo_hygiene_checker.py --format json /path/to/your-repo

# Treat warnings as failures (for CI gates)
python3 src/repo_hygiene_checker.py --strict /path/to/your-repo
```

## Examples

A good repo passes every offline check (exit 0). A bad repo fails five checks (exit 1):

```sh
sh examples/run-example.sh
```

```text
repo-hygiene-checker: examples/bad-repo
PASS  README: README.md present, non-empty, has heading
FAIL  README sections: missing section(s): usage, example
FAIL  Licence (MIT): no licence file found
PASS  .gitignore: .gitignore present, non-empty
FAIL  .gitignore coverage: .gitignore does not cover: __pycache__/ or *.pyc
FAIL  CI runs tests: .github/workflows/ not found
FAIL  Issue templates: no issue template in .github/ISSUE_TEMPLATE/
WARN  CONTRIBUTING.md: CONTRIBUTING.md missing (recommended, not blocking)
WARN  SECURITY.md: SECURITY.md missing (recommended, not blocking)
SKIP  Skill frontmatter: no skills/ directory
WARN  Tests present: no test files in tests/ (recommended, not blocking)
SKIP  GitHub description: needs --online (no network call made)
SKIP  GitHub topics: needs --online (no network call made)
repo-hygiene-checker: 2 passed, 5 failed, 3 warnings, 3 skipped
```

Check this repo against itself (it passes its own gate):

```sh
python3 src/repo_hygiene_checker.py .
```

## How it is tested

20 unit tests, standard library `unittest` only — no third-party packages:

```sh
python3 tests/test_repo_hygiene_checker.py
```

Tests build fixture repos in temp directories (good repo, missing README, non-MIT licence, thin `.gitignore`, workflow without a test step, missing templates, missing CONTRIBUTING, bad SKILL.md frontmatter) and assert the exact status and exit code for each. The `--online` checks run against a real local HTTP server started by the tests, never against the public GitHub API.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Small, focused improvements are welcome; every new check must come with a test, and no status may ever be invented for a check that did not run.

## Licence

MIT — see [LICENSE](LICENSE). This is original work: the checks, the template-conformance idea, and all code were written fresh for this repo. Similar tools are named in "How this differs from similar tools" above; nothing was copied from them.
