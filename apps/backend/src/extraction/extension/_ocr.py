"""OCR / vision model selection and markdown extraction."""

import httpx

import src.config
from src.extraction.extension._base import ExtractionError
from src.llm import LLMError, ocr_layout_call

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


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
        """Run dedicated OCR/layout parsing and return Markdown text.

        The HTTP call itself is `llm`'s ``ocr_layout_call`` (#1670) — a
        non-chat endpoint litellm does not wrap, so it gets its own
        chokepoint in the `llm` package rather than a raw httpx call here.
        """
        file_input = self._build_ai_file_input(file_content, file_url, file_type, mime_type)
        try:
            return await ocr_layout_call(
                base_url=self.base_url,
                layout_parsing_path=settings.ai_layout_parsing_path,
                api_key=self.api_key,
                model=self.ocr_model,
                file_input=file_input,
                timeout=httpx.Timeout(180.0, connect=10.0, read=180.0),
            )
        except LLMError as exc:
            raise ExtractionError(str(exc)) from exc
