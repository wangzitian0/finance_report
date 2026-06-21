"""Violation record."""

from __future__ import annotations

from typing import NamedTuple


class Violation(NamedTuple):
    check: str
    message: str
