"""Document extraction service (package).

Split from a 1903-line ExtractionService god class into mixins; public import
surface preserved. ``httpx`` is imported so monkeypatch of
``src.services.extraction.httpx.AsyncClient`` keeps resolving.
"""

import httpx  # noqa: F401

from src.services.extraction._base import ExtractionError, _tolerant_parse_date
from src.services.extraction.service import ExtractionService

__all__ = ["ExtractionError", "ExtractionService", "_tolerant_parse_date"]
