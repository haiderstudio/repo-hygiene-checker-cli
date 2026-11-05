#!/bin/sh
# Check the bundled examples. Run from the repo root:
#   sh examples/run-example.sh
# Expected: good-repo passes (exit 0), bad-repo fails (exit 1).
set +e
cd "$(dirname "$0")/.."
echo "== good-repo =="
python3 src/repo_hygiene_checker.py examples/good-repo
echo "exit code: $?"
echo ""
echo "== bad-repo =="
python3 src/repo_hygiene_checker.py examples/bad-repo
echo "exit code: $?"
