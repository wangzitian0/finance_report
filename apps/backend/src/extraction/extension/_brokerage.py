"""Brokerage PDF fallback + position backfill."""

from typing import Any

from src.extraction.extension._base import (
    logger,
)
from src.extraction.extension.brokerage_positions import (
    _generated_brokerage_positions_payload_from_text,
    looks_like_brokerage_document,
    parse_brokerage_positions,
)
from src.observability import safe_error_message


class _BrokerageMixin:
    def _extract_pdf_text_for_brokerage_fallback(self, file_content: bytes | None) -> str | None:
        """Extract plain PDF text for deterministic generated brokerage fixture fallback."""
        if not file_content:
            return None
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("PyMuPDF is unavailable; skipping generated brokerage PDF fallback")
            return None
        try:
            document = fitz.open(stream=file_content, filetype="pdf")
        except Exception as exc:
            logger.warning(
                "Generated brokerage PDF text fallback could not read PDF",
                error_type=type(exc).__name__,
                error=safe_error_message(str(exc)),
            )
            return None
        try:
            return "\n".join(page.get_text() or "" for page in document)
        finally:
            document.close()

    def _backfill_generated_brokerage_positions(
        self,
        extracted: dict[str, Any],
        *,
        file_content: bytes | None,
        file_type: str,
        filename: str | None,
        institution: str | None,
    ) -> dict[str, Any]:
        """Recover known generated brokerage positions when the model emits an empty positions list."""
        if file_type != "pdf" or not looks_like_brokerage_document(
            filename=filename,
            institution=institution or extracted.get("institution"),
        ):
            return extracted
        if parse_brokerage_positions(
            extracted, filename=filename, institution=institution or extracted.get("institution")
        ):
            return extracted

        pdf_text = self._extract_pdf_text_for_brokerage_fallback(file_content)
        if not pdf_text:
            return extracted
        fallback = _generated_brokerage_positions_payload_from_text(
            pdf_text,
            filename=filename,
            institution=institution or extracted.get("institution"),
        )
        if not fallback:
            return extracted

        merged = dict(extracted)
        for key in ("institution", "account_last4", "currency", "snapshot_date", "period_start", "period_end"):
            if not merged.get(key):
                merged[key] = fallback.get(key)
        merged["positions"] = fallback["positions"]
        merged.setdefault("transactions", fallback.get("transactions", []))
        logger.info(
            "Backfilled generated brokerage positions from PDF text",
            filename=filename,
            institution=merged.get("institution"),
            positions=len(merged["positions"]),
        )
        return merged
