#!/usr/bin/env python3
"""test-guard: pre_tool_call shell hook (T7 G13, CS Code Project/sdlc/T7-harness-pr-setup).

Agent edits to tests or CI config go to the human-approval gate instead of landing silently.
Why: agents weaken / special-case tests to make them pass (GPT-5 cheated on 76% of impossible
tasks, arXiv 2510.20270); test + CI edits need a human look.

Matches write_file and patch (replace mode `path`, V4A mode `*** Update/Add/Delete File:` lines).
Terminal writes (sed -i, cat >) are NOT covered — the /review pass checks those.
Output: {} = allow · {"action":"approve",...} = ask raymond. Unattended runs fail closed at the gate.
"""
import json
import os
import re
import sys

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|specs?)/"          # test dirs
    r"|(^|/)test_[^/]*\.py$|_test\.(py|go|rs)$"   # python / go / rust test files
    r"|\.(test|spec)\.[cm]?[jt]sx?$"              # js / ts tests
    r"|(^|/)conftest\.py$"
    r"|(^|/)\.github/workflows/"                  # CI config (skipping checks = same cheat)
)


def paths(tool, args):
    if tool == "write_file" or (tool == "patch" and args.get("path")):
        yield args.get("path") or ""
    if tool == "patch" and args.get("patch"):
        for m in re.finditer(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+)$", args["patch"], re.M):
            yield m.group(1).strip()


def main():
    try:
        p = json.load(sys.stdin)
    except Exception:
        print("{}")
        return
    tool = p.get("tool_name") or ""
    args = p.get("tool_input") or {}
    hits = [x for x in paths(tool, args) if x and TEST_PATH.search(x.replace(os.sep, "/"))]
    if not hits:
        print("{}")
        return
    root = os.path.basename(p.get("cwd") or "") or "repo"
    print(json.dumps({
        "action": "approve",
        "message": f"test/CI edit: {', '.join(hits)[:300]} — approve only if the task asked for test changes",
        "rule_key": f"test-guard:{root}",
    }))


if __name__ == "__main__":
    main()
