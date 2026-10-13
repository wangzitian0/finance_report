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
from src.extraction.extension.pdf_text_layer import read_pdf_text_layer


class _BrokerageMixin:
    def _extract_pdf_text_for_brokerage_fallback(self, file_content: bytes | None) -> str | None:
        """Extract plain PDF text for deterministic generated brokerage fixture fallback."""
        return read_pdf_text_layer(file_content)

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
