#!/usr/bin/env python3
"""Generate the machine-readable SLA manifest (finance_report#1654)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools._lib import sla_manifest as _impl  # noqa: E402
from tools._lib.sla_manifest import (  # noqa: E402
    collect_sla_entries as collect_sla_entries,
    render_sla_manifest as render_sla_manifest,
)

SLA_MANIFEST_PATH = _impl.SLA_MANIFEST_PATH


def main(argv: Sequence[str] | None = None) -> int:
    _impl.SLA_MANIFEST_PATH = SLA_MANIFEST_PATH
    _impl.ROOT_DIR = ROOT_DIR
    return _impl.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
