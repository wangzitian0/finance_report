"""Prompts package."""

from src.prompts.statement import (
    INSTITUTION_HINTS,
    SYSTEM_PROMPT,
    VALIDATION_PROMPT,
    get_parsing_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "VALIDATION_PROMPT",
    "INSTITUTION_HINTS",
    "get_parsing_prompt",
]
