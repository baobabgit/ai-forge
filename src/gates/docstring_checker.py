"""Public API docstring verification (EXG-DEV-03, EXG-DOC-01)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard


@dataclass(frozen=True, slots=True)
class MissingDocstring:
    """One public symbol missing a reStructuredText docstring.

    :ivar qualified_name: Fully qualified symbol name.
    :ivar path: Source file path relative to the scan root.
    :ivar line: One-based line number of the symbol definition.
    :ivar kind: Symbol kind (``module``, ``class``, ``function``, ``method``).
    """

    qualified_name: str
    path: str
    line: int
    kind: str


def scan_public_api_docstrings(
    source_root: Path,
    *,
    package_root: Path | None = None,
) -> tuple[MissingDocstring, ...]:
    """Scan Python sources and return public symbols without docstrings.

    Public symbols are module-level definitions and public class methods whose
    names do not start with an underscore.

    :param source_root: Directory tree to scan recursively for ``*.py`` files.
    :param package_root: Optional root used to build relative paths in reports.
    :returns: Missing docstring records sorted by path and line.
    """
    root = source_root.resolve()
    display_root = (package_root or source_root).resolve()
    missing: list[MissingDocstring] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_") or "/tests/" in path.as_posix():
            continue
        rel_path = path.relative_to(display_root).as_posix()
        module_name = rel_path.removesuffix(".py").replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _scan_module(tree, module_name, rel_path, missing)
    return tuple(missing)


def is_rest_docstring(docstring: str | None) -> bool:
    """Return whether ``docstring`` is a non-empty reStructuredText docstring.

    :param docstring: Candidate docstring extracted from an AST node.
    :returns: ``True`` when the docstring is present and non-blank.
    """
    if docstring is None:
        return False
    return bool(docstring.strip())


def _scan_module(
    tree: ast.Module,
    module_name: str,
    rel_path: str,
    missing: list[MissingDocstring],
) -> None:
    if not is_rest_docstring(ast.get_docstring(tree)):
        missing.append(
            MissingDocstring(
                qualified_name=module_name,
                path=rel_path,
                line=1,
                kind="module",
            )
        )
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            _scan_class(node, module_name, rel_path, missing)
        elif _is_public_function(node):
            _record_if_missing(
                node,
                f"{module_name}.{node.name}",
                rel_path,
                "function",
                missing,
            )


def _is_public_function(node: ast.AST) -> TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
        "_"
    )


def _scan_class(
    node: ast.ClassDef,
    module_name: str,
    rel_path: str,
    missing: list[MissingDocstring],
) -> None:
    qualified = f"{module_name}.{node.name}"
    if not node.name.startswith("_"):
        _record_if_missing(node, qualified, rel_path, "class", missing)
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if child.name.startswith("_") and child.name != "__init__":
                continue
            if child.name == "__init__" and is_rest_docstring(ast.get_docstring(node)):
                continue
            method_name = f"{qualified}.{child.name}"
            _record_if_missing(child, method_name, rel_path, "method", missing)


def _record_if_missing(
    node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    qualified_name: str,
    rel_path: str,
    kind: str,
    missing: list[MissingDocstring],
) -> None:
    if not is_rest_docstring(ast.get_docstring(node)):
        line = getattr(node, "lineno", 1)
        missing.append(
            MissingDocstring(
                qualified_name=qualified_name,
                path=rel_path,
                line=line,
                kind=kind,
            )
        )
