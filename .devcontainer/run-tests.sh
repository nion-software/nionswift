#!/bin/bash
# Run the test suites for all packages that have them.
# Usage: bash .devcontainer/run-tests.sh [pytest args...]

TEST_REPOS="nionutils niondata nionui nionswift nionswift-instrumentation-kit nionswift-usim"

failed=""
for r in $TEST_REPOS; do
  echo "=== $r"
  python -m pytest "/workspaces/$r" -q "$@" || failed="$failed $r"
done

if [ -n "$failed" ]; then
  echo "FAILED:$failed"
  exit 1
fi
echo "All suites passed."
