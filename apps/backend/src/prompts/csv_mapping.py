"""EPIC-018 Phase 4: AI prompt for CSV column mapping of unknown institutions."""

CSV_MAPPING_PROMPT = """You are a financial CSV parser.
Given a CSV header row and up to 5 sample data rows, identify which columns contain:
- date: Transaction date
- description: Transaction description/narrative
- amount: Transaction amount (single column with +/- or absolute value)
- debit: Debit/withdrawal amount (if separate columns)
- credit: Credit/deposit amount (if separate columns)
- balance: Running balance after transaction
- reference: Transaction reference number
- currency: Transaction currency

CRITICAL: Return ONLY a JSON object, no markdown, no extra text:
{
  "date": "Column Name",
  "description": "Column Name",
  "amount": "Column Name or null if separate debit/credit",
  "debit": "Column Name or null",
  "credit": "Column Name or null",
  "balance": "Column Name or null",
  "reference": "Column Name or null",
  "currency": "Column Name or null",
  "date_format": "auto-detected format like %d/%m/%Y or %Y-%m-%d",
  "has_header": true,
  "institution_guess": "Best guess of the institution name"
}

Rules:
- If amounts are in a single column (positive=credit, negative=debit), set "amount" and leave debit/credit null
- If amounts are in separate debit/credit columns, set those and leave "amount" null
- Set columns to null if not found
- Use exact column header names from the CSV
"""


def build_csv_mapping_prompt(headers: list[str], sample_rows: list[list[str]]) -> str:
    """Build prompt for AI CSV column mapping.

    Args:
        headers: List of CSV column headers
        sample_rows: Up to 5 sample data rows

    Returns:
        Formatted prompt string
    """
    header_line = " | ".join(headers)
    sample_lines = "\n".join(" | ".join(row) for row in sample_rows[:5])

    return f"""{CSV_MAPPING_PROMPT}

CSV Headers: {header_line}

Sample Data:
{sample_lines}

Return your JSON mapping:"""
