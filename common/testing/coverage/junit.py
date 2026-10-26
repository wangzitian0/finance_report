"""JUnit XML parser single source of truth.

This module provides common utilities to parse and inspect JUnit XML reports.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree


def parse_junit_root(path: Path) -> ElementTree.Element | None:
    """Parse a JUnit XML file and return its root element safely."""
    if not path.is_file():
        return None
    try:
        tree = ElementTree.parse(path)
        return tree.getroot()
    except (OSError, ElementTree.ParseError):
        return None


def iter_testcases(source: Path | ElementTree.Element) -> list[ElementTree.Element]:
    """Extract all testcase elements from an XML path or root element."""
    if isinstance(source, Path):
        root = parse_junit_root(source)
    else:
        root = source

    if root is None:
        return []

    return list(root.iter("testcase"))
