#!/usr/bin/env python3
"""Command wrapper for the common/ directory-coverage governance gate.

Every directory directly under ``common/`` must either ship a ``contract.py``
(a declared package, checked by ``check_package_contract.py``) or be a
documented exception in ``UNGOVERNED_EXCEPTIONS``. See
``common/meta/extension/check_package_directory_coverage.py`` and
``common/meta/readme.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.meta.extension.check_package_directory_coverage import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
