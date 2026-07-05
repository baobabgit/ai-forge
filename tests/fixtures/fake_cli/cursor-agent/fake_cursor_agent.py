#!/usr/bin/env python3
"""Fake Cursor Agent CLI used by provider adapter tests."""

from __future__ import annotations

import json
import sys


def _parse_args(argv: list[str]) -> tuple[str, bool, bool]:
    mode = ""
    fail_auth = False
    wrong_model = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"-p", "--print"} and index + 1 < len(argv):
            mode = argv[index + 1]
            index += 2
            continue
        if arg == "--fail-auth":
            fail_auth = True
            index += 1
            continue
        if arg == "--wrong-model":
            wrong_model = True
            index += 1
            continue
        if arg.startswith("--"):
            index += 2 if index + 1 < len(argv) and not argv[index + 1].startswith("-") else 1
            continue
        mode = arg
        index += 1
    return mode, fail_auth, wrong_model


def main() -> int:
    mode, fail_auth, wrong_model = _parse_args(sys.argv[1:])

    if mode == "plain-health-check":
        print("authenticated without json")
        return 0

    if mode == "health-check":
        if fail_auth:
            print("not authenticated", file=sys.stderr)
            return 1
        model = "wrong-model" if wrong_model else "auto"
        print(json.dumps({"model": model, "authenticated": True}))
        return 0

    if mode == "ok":
        print(json.dumps({"result": "completed successfully", "is_error": False}))
        return 0

    if mode == "text-ok":
        print("plain text success")
        return 0

    if mode == "exhausted":
        print("request limit reached for this subscription", file=sys.stderr)
        return 1

    if mode == "error":
        print("unexpected provider failure", file=sys.stderr)
        return 2

    if mode == "hang":
        import time

        time.sleep(60)
        return 0

    print(f"unknown mode {mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
