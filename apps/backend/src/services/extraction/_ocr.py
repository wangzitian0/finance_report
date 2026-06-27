"""OCR / vision model selection and markdown extraction."""

import httpx

from src.config import settings
from src.observability import safe_error_message
from src.services.extraction._base import (
    ExtractionError,
    logger,
)


class _OcrMixin:
    def _uses_dedicated_layout_ocr(self) -> bool:
        """Use the layout parser only when OCR is configured as a separate model."""
        return bool(self.ocr_model and self.ocr_model != self.vision_model)

    def _vision_extraction_models(self) -> list[str]:
        """Return ordered vision/OCR models without duplicate provider calls.

        The primary OCR/vision models are followed by the configured
        ``VISION_FALLBACK_MODELS`` so a non-retryable failure of the primary
        vision model (e.g. a provider 400) falls through to a secondary
        vision-capable model before the upload is rejected (#1034). The list is
        deduplicated and order-preserving. Text-only ``FALLBACK_MODELS`` are not
        reused here because the vision request carries image content.
        """
        models: list[str] = []
        for model in (self.ocr_model, self.vision_model, *self.vision_fallback_models):
            if model and model not in models:
                models.append(model)
        return models

    async def _extract_ocr_markdown(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
    ) -> str:
        """Run dedicated OCR/layout parsing and return Markdown text."""
        file_input = self._build_ai_file_input(file_content, file_url, file_type, mime_type)
        layout_url = f"{self.base_url.rstrip('/')}/{settings.ai_layout_parsing_path.lstrip('/')}"
        payload = {
            "model": self.ocr_model,
            "file": file_input,
            "return_crop_images": False,
            "need_layout_visualization": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Sending document to OCR layout parser",
            provider=settings.ai_provider,
            model=self.ocr_model,
            file_type=file_type,
            data_source="base64" if file_input.startswith("data:") else "url",
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0, read=180.0)) as client:
            response = await client.post(layout_url, headers=headers, json=payload)

        if response.status_code != 200:
            safe_summary = safe_error_message(response.text)
            logger.error(
                "OCR layout parsing failed",
                provider=settings.ai_provider,
                model=self.ocr_model,
                status_code=response.status_code,
                safe_error_message=safe_summary,
            )
            raise ExtractionError(f"OCR layout parsing failed: HTTP {response.status_code}: {safe_summary}")

        result = response.json()
        markdown = result.get("md_results")
        if isinstance(markdown, list):
            markdown = "\n\n".join(str(item) for item in markdown if item)
        if not isinstance(markdown, str) or not markdown.strip():
            raise ExtractionError("OCR layout parsing returned empty Markdown")

        logger.info(
            "OCR layout parsing completed",
            provider=settings.ai_provider,
            model=self.ocr_model,
            markdown_length=len(markdown),
        )
        return markdown
