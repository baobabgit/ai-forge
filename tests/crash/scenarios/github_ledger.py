"""File-backed fake GitHub ledger recording pull-request side effects.

The crash harness must prove that a resumed run produces **no duplicate GitHub
side effect** (EXG-NF-01). This ledger is the observable "GitHub": every PR
creation and merge is appended to a JSON file shared between the killed driver
process and the test process, so the test can count real side effects across
the crash boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeGitHubLedger:
    """Append-only JSON ledger of pull-request operations."""

    def __init__(self, path: Path) -> None:
        """Bind the ledger to its backing file.

        :param path: JSON file shared between processes.
        """
        self._path = path

    def create_pr(self, branch: str) -> int:
        """Record a pull-request creation and return its number.

        :param branch: Head branch of the new pull request.
        :returns: The allocated pull-request number.
        """
        ops = self._load()
        number = sum(1 for op in ops if op["op"] == "create_pr") + 1
        ops.append({"op": "create_pr", "branch": branch, "number": number})
        self._save(ops)
        return number

    def merge_pr(self, number: int) -> None:
        """Record the merge of pull request ``number``.

        :param number: Pull-request number to merge.
        """
        ops = self._load()
        ops.append({"op": "merge_pr", "number": number})
        self._save(ops)

    def open_pr_for(self, branch: str) -> int | None:
        """Return the open (created, not merged) PR number for ``branch``.

        :param branch: Head branch to look up.
        :returns: The open pull-request number, or ``None``.
        """
        ops = self._load()
        merged = {op["number"] for op in ops if op["op"] == "merge_pr"}
        for op in reversed(ops):
            if op["op"] == "create_pr" and op["branch"] == branch:
                number = int(op["number"])
                return None if number in merged else number
        return None

    def merged_pr_for(self, branch: str) -> int | None:
        """Return the merged PR number for ``branch``, if any.

        :param branch: Head branch to look up.
        :returns: The merged pull-request number, or ``None``.
        """
        ops = self._load()
        merged = {op["number"] for op in ops if op["op"] == "merge_pr"}
        for op in reversed(ops):
            if op["op"] == "create_pr" and op["branch"] == branch:
                number = int(op["number"])
                return number if number in merged else None
        return None

    def count(self, op: str) -> int:
        """Return how many operations of kind ``op`` were recorded.

        :param op: Operation kind (``create_pr`` or ``merge_pr``).
        :returns: The operation count.
        """
        return sum(1 for entry in self._load() if entry["op"] == op)

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        return list(loaded) if isinstance(loaded, list) else []

    def _save(self, ops: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(ops, indent=2), encoding="utf-8")
