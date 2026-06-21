#!/usr/bin/env python3
"""Command wrapper for the package-contract governance gate.

Validates every package's ``common/<pkg>/contract.py`` (a ``PackageContract``)
against its BE implementation: published language (``interface`` == the
implementation's ``__all__``), every invariant/roadmap test resolves, and no
forbidden dependency edge. See ``common/governance/check_package_contract.py``
and ``common/governance/readme.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.governance.check_package_contract import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
