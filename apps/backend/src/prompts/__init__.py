"""Prompts package (advisor).

The statement/CSV-mapping parsing prompts moved into the extraction package
(#1421): import them via ``from src.extraction import get_parsing_prompt,
SYSTEM_PROMPT`` or the package's prompts modules, not from here. The
reconciliation semantic-scoring prompt moved into the reconciliation package
(#1670): import it via ``from src.reconciliation import
build_reconciliation_prompt``.
"""

from src.prompts.ai_advisor import get_ai_advisor_prompt

__all__ = ["get_ai_advisor_prompt"]
