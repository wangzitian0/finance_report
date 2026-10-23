"""OCR / vision model selection and markdown extraction."""

import httpx

import src.config
from src.extraction.extension._base import ExtractionError
from src.llm import LLMError, ocr_layout_call

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


class _OcrMixin:
    # Provided by ExtractionService and the other mixins; declared here for the type checker.
    api_key: str | None
    base_url: str
    ocr_model: str
    vision_model: str

    def _build_ai_file_input(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
        *,
        prefer_url: bool = False,
    ) -> str:
        raise NotImplementedError

    def _uses_dedicated_layout_ocr(self) -> bool:
        """Use the layout parser only when OCR is configured as a separate model."""
        return bool(self.ocr_model and self.ocr_model != self.vision_model)

    def _vision_extraction_models(self) -> list[str]:
        """Return the vision/OCR models without duplicate provider calls.

        The multimodal role serves both, so this is one model. There is no fallback
        chain: the owner rule bans older fallback models. The list is deduplicated.
        """
        models: list[str] = []
        for model in (self.ocr_model, self.vision_model):
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
                api_key=self.api_key or "",
                model=self.ocr_model,
                file_input=file_input,
                timeout=httpx.Timeout(180.0, connect=10.0, read=180.0),
            )
        except LLMError as exc:
            raise ExtractionError(str(exc)) from exc
