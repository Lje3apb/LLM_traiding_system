#!/usr/bin/env python3
"""Script to check documentation quality across the codebase."""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

class DocstringChecker(ast.NodeVisitor):
    """Check for missing docstrings and type hints."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.issues: List[Tuple[int, str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function for docstring and type hints."""
        # Skip private functions (starting with _)
        if node.name.startswith('_') and not node.name.startswith('__'):
            self.generic_visit(node)
            return

        # Check for docstring
        docstring = ast.get_docstring(node)
        if not docstring:
            self.issues.append((
                node.lineno,
                node.name,
                f"Missing docstring for public function '{node.name}'"
            ))

        # Check return type hint
        if node.returns is None and node.name != '__init__':
            self.issues.append((
                node.lineno,
                node.name,
                f"Missing return type hint for '{node.name}'"
            ))

        # Check argument type hints (skip self, cls)
        for arg in node.args.args:
            if arg.arg in ('self', 'cls'):
                continue
            if arg.annotation is None:
                self.issues.append((
                    node.lineno,
                    node.name,
                    f"Missing type hint for argument '{arg.arg}' in '{node.name}'"
                ))

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function for docstring and type hints."""
        # Reuse same logic as regular functions
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check class for docstring."""
        # Skip private classes
        if node.name.startswith('_'):
            self.generic_visit(node)
            return

        docstring = ast.get_docstring(node)
        if not docstring:
            self.issues.append((
                node.lineno,
                node.name,
                f"Missing docstring for public class '{node.name}'"
            ))

        self.generic_visit(node)


def check_file(filepath: Path) -> List[Tuple[int, str, str]]:
    """Check a single Python file for documentation issues."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        checker = DocstringChecker(filepath)
        checker.visit(tree)
        return checker.issues
    except SyntaxError as e:
        return [(e.lineno or 0, "SYNTAX_ERROR", f"Syntax error: {e}")]
    except Exception as e:
        return [(0, "ERROR", f"Error parsing file: {e}")]


def main():
    """Main entry point."""
    # Focus on core modules
    modules_to_check = [
        "llm_trading_system/strategies",
        "llm_trading_system/engine",
        "llm_trading_system/exchange",
        "llm_trading_system/core",
        "llm_trading_system/data",
        "llm_trading_system/api",
        "llm_trading_system/config",
    ]

    all_issues = {}
    total_issues = 0

    for module_path in modules_to_check:
        module_dir = Path(module_path)
        if not module_dir.exists():
            continue

        for py_file in module_dir.rglob("*.py"):
            # Skip __pycache__ and test files
            if "__pycache__" in str(py_file) or "test_" in py_file.name:
                continue

            issues = check_file(py_file)
            if issues:
                all_issues[str(py_file)] = issues
                total_issues += len(issues)

    # Print results
    print(f"\n{'='*80}")
    print(f"DOCUMENTATION QUALITY CHECK")
    print(f"{'='*80}\n")

    if not all_issues:
        print("✅ No documentation issues found!")
        return 0

    print(f"Found {total_issues} documentation issues across {len(all_issues)} files:\n")

    for filepath, issues in sorted(all_issues.items()):
        print(f"\n{filepath}:")
        for lineno, name, message in sorted(issues):
            print(f"  Line {lineno:4d} | {message}")

    print(f"\n{'='*80}")
    print(f"Total issues: {total_issues}")
    print(f"{'='*80}\n")

    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
