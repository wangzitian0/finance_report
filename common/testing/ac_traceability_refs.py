#!/usr/bin/env python3
"""Shared AC reference classification helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

# Matches both id grammars: legacy ``AC{epic}.{n}.{n}`` and package-scoped
# ``AC-{package}.{group}.{n}``, where ``group`` is either numeric (continuing
# an EPIC's own numbering) or a word-entity slug (e.g. ``guardrail``,
# ``fx-transfer``) — packages use whichever convention fits their roadmap.
AC_PATTERN = re.compile(
    r"\bAC(?:\d+\.\d+\.\d+|-[a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_-]*\.\d+)\b"
)

ReferenceKind = Literal["real", "stub", "placeholder"]

_TRIVIAL_EXPECT_RE = re.compile(
    r"\bexpect\s*\(\s*true\s*\)\s*\.\s*to(?:Be|Equal)\s*\(\s*true\s*\)",
    re.IGNORECASE,
)
_PYTEST_SKIP_RE = re.compile(r"\bpytest\.skip\s*\(", re.IGNORECASE)
_JS_SKIP_RE = re.compile(r"\b(?:it|test|describe)\.skip\s*\(", re.IGNORECASE)
_PY_PASS_RE = re.compile(r"^\s*pass(?:\s*#.*)?$", re.MULTILINE)
_ASSERTION_TOKENS = (
    "assert ",
    "assert(",
    "expect(",
    "expect.",
    "screen.",
    "render(",
    "client.",
    "page.",
    "await ",
    ".click(",
    ".fill(",
    ".get(",
    ".post(",
    ".patch(",
    ".put(",
    ".delete(",
)


def is_stub_file(path: Path) -> bool:
    """Return True for generated AC reference stubs."""
    return "_ac_stubs" in path.parts


def is_placeholder_file(path: Path, content: str) -> bool:
    """Return True for test files that only provide placeholder assertions.

    The heuristic is deliberately narrow. Environment-gated E2E files may
    contain skip calls and still assert real behavior when configured. Pure
    pass/skip files are only classified as placeholder when they contain AC
    references and no behavioral assertion or interaction tokens.
    """
    if is_stub_file(path):
        return False
    if not AC_PATTERN.search(content):
        return False
    content_without_trivial_expect = _TRIVIAL_EXPECT_RE.sub("", content)
    if _TRIVIAL_EXPECT_RE.search(content) and not any(
        token in content_without_trivial_expect for token in _ASSERTION_TOKENS
    ):
        return True
    if any(token in content for token in _ASSERTION_TOKENS):
        return False
    return bool(
        _PY_PASS_RE.search(content)
        or _PYTEST_SKIP_RE.search(content)
        or _JS_SKIP_RE.search(content)
    )


def classify_reference_file(path: Path, content: str) -> ReferenceKind:
    """Classify how AC references from one test file should be counted."""
    if is_stub_file(path):
        return "stub"
    if is_placeholder_file(path, content):
        return "placeholder"
    return "real"
