#!/usr/bin/env python3
"""Command wrapper for real-corpus re-verification against live extraction (#1744).

Owns the concrete live extractor (imports apps/backend's ExtractionService)
deliberately OUTSIDE common/testing/reverify_real_corpus.py: that module is
infra-tier and must not import a specific domain package's extraction code —
tools/ is unregistered and free to combine both.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from common.testing.reverify_real_corpus import main as _reverify_main  # noqa: E402


def _live_extractor(pdf_path: Path) -> dict[str, Any] | None:
    """The real extraction call — imports lazily so importing this module (or
    common/testing/reverify_real_corpus.py's unit tests) never needs the
    backend app package importable, and requires the operator's own event
    loop (this function is sync; main() runs synchronously)."""
    import asyncio

    async def _run() -> dict[str, Any] | None:
        from src.extraction.extension.service import ExtractionError, ExtractionService

        service = ExtractionService()
        if not service.api_key:
            return None
        try:
            return await service.extract_financial_data(
                file_content=pdf_path.read_bytes(),
                institution=None,
                file_type="pdf",
                filename=pdf_path.name,
            )
        except ExtractionError:
            return None

    return asyncio.run(_run())


def main(argv: list[str] | None = None) -> int:
    return _reverify_main(argv, live_extractor=_live_extractor)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
