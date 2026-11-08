#!/bin/sh
# run every test file in its own interpreter
# (test_agent_core spawns real processes for race tests; on macOS a forked child that touched CoreFoundation
#  can poison the next file in a shared run, so 1 file = 1 process keeps results independent)
set -u
cd "$(dirname "$0")/.."
fail=0
for t in tests/test_*.py; do
  python3 -m pytest -q -p no:cacheprovider "$t" || fail=1
done
exit $fail
