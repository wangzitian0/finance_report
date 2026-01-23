"""Prompts package."""

from src.prompts.ai_advisor import get_ai_advisor_prompt
from src.prompts.statement import (
    INSTITUTION_HINTS,
    SYSTEM_PROMPT,
    VALIDATION_PROMPT,
    get_parsing_prompt,
)

__all__ = [
    "INSTITUTION_HINTS",
    "SYSTEM_PROMPT",
    "VALIDATION_PROMPT",
    "get_ai_advisor_prompt",
    "get_parsing_prompt",
]
