#!/usr/bin/env python3
"""Render a validated Finance Report fixed-environment request without side effects."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools._lib.deploy import app_deploy_request as _impl  # noqa: E402
from tools._lib.deploy.app_deploy_request import (  # noqa: E402
    SOURCE_REPOSITORY as SOURCE_REPOSITORY,
    _SOURCE_RUN_PATH_RE as _SOURCE_RUN_PATH_RE,
    canonical_json as canonical_json,
    render_request as render_request,
    request_from_mapping as request_from_mapping,
)


def main(argv: Sequence[str] | None = None) -> int:
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
