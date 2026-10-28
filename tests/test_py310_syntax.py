from __future__ import annotations

import ast
import pathlib
import sys
from typing import List

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"

BANNED_MODULES = {
    "aifc",
    "asynchat",
    "asyncore",
    "cgi",
    "cgitb",
    "chunk",
    "crypt",
    "imghdr",
    "mailcap",
    "msilib",
    "nntplib",
    "nis",
    "ossaudiodev",
    "pipes",
    "smtpd",
    "sndhdr",
    "spwd",
    "sunau",
    "telnetlib",
    "uu",
    "xdrlib",
}


class Py310CompatibilityScanner(ast.NodeVisitor):
    """AST scanner enforcing Python 3.10 syntax constraints across modern Python interpreters."""

    def __init__(self, filename: str, source: str) -> None:
        self.filename = filename
        self.source = source
        self.lines = source.splitlines()
        self.violations: List[str] = []

    def visit_FormattedValue(self, node: ast.FormattedValue) -> None:
        """Reject backslashes inside f-string replacement expressions (PEP 701 regression)."""
        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
            expr_lines = self.lines[node.lineno - 1 : node.end_lineno]
            if expr_lines:
                if len(expr_lines) == 1:
                    segment = expr_lines[0][node.col_offset : node.end_col_offset]
                else:
                    expr_lines[0] = expr_lines[0][node.col_offset :]
                    expr_lines[-1] = expr_lines[-1][: node.end_col_offset]
                    segment = "\n".join(expr_lines)
                if "\\" in segment:
                    self.violations.append(
                        f"{self.filename}:{node.lineno}: Backslash in f-string expression is forbidden in Python 3.10 ({segment!r})"
                    )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Reject deprecated and removed standard library modules."""
        for alias in node.names:
            top_level = alias.name.split(".")[0]
            if top_level in BANNED_MODULES:
                self.violations.append(
                    f"{self.filename}:{node.lineno}: Import of removed standard library module '{top_level}'"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Reject deprecated and removed standard library modules."""
        if node.module:
            top_level = node.module.split(".")[0]
            if top_level in BANNED_MODULES:
                self.violations.append(
                    f"{self.filename}:{node.lineno}: Import from removed standard library module '{top_level}'"
                )
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        """Inspect general AST nodes for Python 3.12+ features."""
        if node.__class__.__name__ == "TypeAlias":
            lineno = getattr(node, "lineno", 0)
            self.violations.append(
                f"{self.filename}:{lineno}: PEP 695 'type' statement is forbidden in Python 3.10"
            )

        if hasattr(node, "type_params") and getattr(node, "type_params"):
            lineno = getattr(node, "lineno", 0)
            name = getattr(node, "name", "<anonymous>")
            self.violations.append(
                f"{self.filename}:{lineno}: PEP 695 type parameters on '{name}' are forbidden in Python 3.10"
            )

        super().generic_visit(node)


def get_all_python_files() -> List[pathlib.Path]:
    """Retrieve all Python source files in the repository."""
    src_files = list(SRC_DIR.rglob("*.py"))
    test_files = list(TESTS_DIR.rglob("*.py"))
    return sorted(src_files + test_files)


def test_all_source_and_test_files_compile() -> None:
    """Verify that every python file compiles cleanly and satisfies Python 3.10 constraints."""
    py_files = get_all_python_files()
    assert len(py_files) > 0, "No python files found in repository"

    all_violations: List[str] = []

    for file_path in py_files:
        content = file_path.read_text(encoding="utf-8")

        # 1. Bytecode compilation check
        try:
            compile(content, str(file_path), "exec")
        except SyntaxError as exc:
            all_violations.append(f"{file_path}:{exc.lineno}: SyntaxError: {exc.msg}")
            continue

        # 2. AST inspection
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as exc:
            all_violations.append(f"{file_path}:{exc.lineno}: AST Parse Error: {exc.msg}")
            continue

        scanner = Py310CompatibilityScanner(str(file_path), content)
        scanner.visit(tree)
        all_violations.extend(scanner.violations)

    assert not all_violations, f"Found {len(all_violations)} Python 3.10 compatibility violation(s):\n" + "\n".join(all_violations)


def test_scanner_detects_fstring_backslash() -> None:
    """Verify that scanner flags backslashes in f-string expressions."""
    if sys.version_info < (3, 12):
        # On Python < 3.12, f-string with backslash is a SyntaxError at compile time
        with pytest.raises(SyntaxError):
            ast.parse('f"{\'\\\\n\'.join(items)}"')
    else:
        source = 'items = ["a", "b"]\nmsg = f"{\'\\n\'.join(items)}"\n'
        tree = ast.parse(source)
        scanner = Py310CompatibilityScanner("<synthetic>", source)
        scanner.visit(tree)
        assert len(scanner.violations) == 1
        assert "Backslash in f-string expression" in scanner.violations[0]


def test_scanner_detects_type_alias_pep695() -> None:
    """Verify that scanner flags PEP 695 type aliases."""
    if sys.version_info >= (3, 12):
        source = "type MyInt = int\n"
        tree = ast.parse(source)
        scanner = Py310CompatibilityScanner("<synthetic>", source)
        scanner.visit(tree)
        assert len(scanner.violations) == 1
        assert "PEP 695 'type' statement" in scanner.violations[0]


def test_scanner_detects_banned_modules() -> None:
    """Verify that scanner flags removed/deprecated standard library modules."""
    source = "import cgi\nfrom pipes import quote\n"
    tree = ast.parse(source)
    scanner = Py310CompatibilityScanner("<synthetic>", source)
    scanner.visit(tree)
    assert len(scanner.violations) == 2
    assert any("module 'cgi'" in v for v in scanner.violations)
    assert any("module 'pipes'" in v for v in scanner.violations)
