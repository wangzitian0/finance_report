#!/usr/bin/env python3
"""Shared AC reference classification helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

AC_PATTERN = re.compile(r"\bAC\d+\.\d+\.\d+\b")

ReferenceKind = Literal["real", "stub", "placeholder"]

_TRIVIAL_EXPECT_RE = re.compile(
    r"\bexpect\s*\(\s*true\s*\)\s*\.\s*to(?:Be|Equal)\s*\(\s*true\s*\)",
    re.IGNORECASE,
)


def is_stub_file(path: Path) -> bool:
    """Return True for generated AC reference stubs."""
    return "_ac_stubs" in path.parts


def is_placeholder_file(path: Path, content: str) -> bool:
    """Return True for test files that only provide placeholder assertions.

    The heuristic is deliberately narrow. Environment-gated E2E files may
    contain skip calls and still assert real behavior when configured, so this
    only flags explicit no-op assertions used by known AC placeholder files.
    """
    if is_stub_file(path):
        return False
    return bool(_TRIVIAL_EXPECT_RE.search(content))


def classify_reference_file(path: Path, content: str) -> ReferenceKind:
    """Classify how AC references from one test file should be counted."""
    if is_stub_file(path):
        return "stub"
    if is_placeholder_file(path, content):
        return "placeholder"
    return "real"
