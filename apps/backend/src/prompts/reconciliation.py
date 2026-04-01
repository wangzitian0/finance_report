"""EPIC-018 Phase 3: AI reconciliation prompt for semantic similarity scoring."""

RECONCILIATION_SEMANTIC_PROMPT = """You are a financial transaction matching expert.
Given two transaction descriptions, rate their semantic similarity on a 0-100 scale.

Consider:
- Whether they refer to the same merchant, payee, or transaction type
- Matching reference numbers, invoice numbers, or identifiers
- Similar transaction patterns (e.g., "SALARY ACME" matches "Payroll - Acme Corp")
- Date proximity and amount similarity as context clues

Context provided:
- Bank transaction description and journal entry memo
- Date proximity (days apart)
- Amount match percentage

CRITICAL: Return ONLY a JSON object, no markdown, no extra text:
{
  "similarity_score": 85,
  "reasoning": "Both refer to salary payment from same employer"
}

Rules:
- Score 90-100: Clear same transaction (same merchant, reference, or pattern)
- Score 70-89: Likely same transaction (similar merchant, compatible amounts)
- Score 50-69: Possibly related (same category, different details)
- Score 0-49: Unlikely to be the same transaction
"""


def build_reconciliation_prompt(
    txn_description: str,
    entry_memo: str,
    date_diff_days: int,
    amount_match_pct: float,
) -> str:
    """Build the prompt for AI semantic scoring of a reconciliation candidate.

    Args:
        txn_description: Bank transaction description
        entry_memo: Journal entry memo
        date_diff_days: Absolute days between transaction and entry dates
        amount_match_pct: Amount match percentage (0-100)

    Returns:
        Formatted prompt string for the AI model
    """
    return f"""{RECONCILIATION_SEMANTIC_PROMPT}

Now evaluate this pair:

Bank Transaction: "{txn_description}"
Journal Entry: "{entry_memo}"
Date difference: {date_diff_days} days apart
Amount match: {amount_match_pct:.0f}%

Return your JSON assessment:"""
