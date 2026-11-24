"""Enums of the stored LLM configuration (``llm_providers``, ``llm_scene_bindings``).

The two tables have no reader since #2953 stage 2; the migration that drops them (stage 3) is owner-reserved. These
enums stay only for the ORM models of ``llm/orm/config.py`` until that migration removes both.
"""

from __future__ import annotations

from enum import StrEnum


class ProtocolFamily(StrEnum):
    """Axis 1 — the wire protocol a provider speaks.

    Concrete vendors map onto exactly one family; e.g. Z.AI/GLM and DeepSeek are
    ``OPENAI_COMPATIBLE`` (custom ``api_base``), Claude is ``ANTHROPIC_COMPATIBLE``,
    and Google Gemini (AI Studio / Vertex) is ``GOOGLE_GEMINI`` — its native API
    accepts a whole PDF as one ``file`` part (no per-page image rendering) and has
    a high output ceiling, which is why it is the provider of choice for extracting
    large or scanned statements.
    """

    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC_COMPATIBLE = "anthropic-compatible"
    OPENROUTER_COMPATIBLE = "openrouter-compatible"
    GOOGLE_GEMINI = "google-gemini"


class Scene(StrEnum):
    """Axis 3 — a code-defined call site. Adding one is a contract change.

    The value is the stable identifier persisted in bindings; keep it in sync
    with ``common/llm/readme.md``.
    """

    EXTRACTION_OCR = "extraction.ocr"
    EXTRACTION_VISION = "extraction.vision"
    EXTRACTION_JSON = "extraction.json"
    ADVISOR_CHAT = "advisor.chat"
    STATEMENT_SUMMARY = "statement.summary"


class ReasoningEffort(StrEnum):
    """Per-scene reasoning depth of a stored binding."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
