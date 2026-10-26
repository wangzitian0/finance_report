"""OCR / vision model selection."""


class _OcrMixin:
    # Provided by ExtractionService; declared here for the type checker.
    ocr_model: str
    vision_model: str

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
