"""JUnit XML parser and merge single source of truth.

This module provides common utilities to parse, inspect, and merge JUnit XML reports.
"""

from __future__ import annotations

from collections.abc import Sequence
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


def extract_testsuites(source: Path | ElementTree.Element) -> list[ElementTree.Element]:
    """Extract testsuite elements from an XML path or root element."""
    if isinstance(source, Path):
        root = parse_junit_root(source)
    else:
        root = source

    if root is None:
        return []

    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        return list(root)
    return [root]


def iter_testcases(source: Path | ElementTree.Element) -> list[ElementTree.Element]:
    """Extract all testcase elements from an XML path or root element."""
    if isinstance(source, Path):
        root = parse_junit_root(source)
    else:
        root = source

    if root is None:
        return []

    return list(root.iter("testcase"))


def merge_junit_files(input_paths: Sequence[Path], output_path: Path) -> int:
    """Merge testsuite elements from input paths into output path."""
    valid_paths = [p for p in input_paths if p.is_file()]
    if not valid_paths:
        print(f"Error: no valid JUnit XML files found among {input_paths}")
        return 1

    merged_root = ElementTree.Element("testsuites")
    for path in valid_paths:
        root = parse_junit_root(path)
        if root is None:
            print(f"Warning: failed to parse {path}")
            continue
        if root.tag == "testsuite":
            merged_root.append(root)
        elif root.tag == "testsuites":
            merged_root.extend(list(root))
        else:
            merged_root.append(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(merged_root).write(
        str(output_path), encoding="utf-8", xml_declaration=True
    )
    print(f"Merged {len(valid_paths)} shard junit files into {output_path}")
    return 0
