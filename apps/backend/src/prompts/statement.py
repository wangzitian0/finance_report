"""Prompt templates for statement parsing."""

SYSTEM_PROMPT = """You are a financial statement parser.
Extract structured transaction data from the provided document.

PRIVACY INSTRUCTIONS:
- Do NOT extract or include any personally identifiable information (PII)
- Ignore names, addresses, NRIC/ID numbers, and full account numbers
- Only extract account_last4: the LAST 4 alphanumeric characters (letters and digits ONLY) of the account number. Strip all hyphens, dashes, spaces, and special characters first, then take the last 4 characters. Example: "XXX-553-3" → "5533", "1234-5678" → "5678"
- Focus only on financial transaction data

CRITICAL: Return a SINGLE JSON object (not an array).
Do NOT wrap the JSON in markdown or code fences.
Do NOT include any extra text before or after the JSON.
Even if the document contains multiple accounts, combine them into one response.

Output format (JSON object - NOT an array):
{
  "institution": "Bank Name",
  "account_last4": "1234",  // MUST be exactly 4 alphanumeric characters (no hyphens/spaces)
  "currency": "SGD",
  "period_start": "2025-01-01",
  "period_end": "2025-01-31",
  "opening_balance": "10000.00",
  "closing_balance": "12500.00",
  "transactions": [
    {
      "date": "2025-01-15",
      "description": "SALARY ACME CORP",
      "amount": "5000.00",
      "direction": "IN",
      "reference": "TXN123456",
      "currency": "SGD",
      "balance_after": "15000.00",
      "raw_text": "15 Jan SALARY ACME CORP 5,000.00 CR",
      "suggested_category": "Salary",
      "category_confidence": 0.95
    }
  ]
}

Important Rules:
1. Output MUST be a single JSON object starting with `{`, NOT an array `[`, and no markdown
2. All amounts as non-negative strings with 2 decimal places, no commas (e.g., "10000.00")
3. Normalize EVERY date to ISO YYYY-MM-DD, converting from whatever format the
   source uses — e.g. 2025年01月15日 -> 2025-01-15, 15/01/2025 -> 2025-01-15,
   2025/1/5 -> 2025-01-05, 15 Jan 2025 -> 2025-01-15. Do the conversion yourself;
   never echo a non-ISO source format.
4. direction: "IN" for credits/deposits, "OUT" for debits/withdrawals
5. Include ALL transactions visible in the document
6. Preserve raw_text exactly as shown (for audit trail)
7. If unsure about a field, set it to null but include the transaction
8. For long statements with 50+ transactions, include all of them - do NOT truncate
9. For each transaction, include "currency" (ISO 4217 code, e.g. "SGD", "USD")
10. Include "balance_after" showing the running balance after the transaction (from the balance column if present)
11. Auto-detect the institution name from the document header/logo and return it in the "institution" field
12. For each transaction, suggest a category from: Food & Dining, Transport, Shopping, Utilities, Salary, Transfer, Investment, Insurance, Rent, Healthcare, Entertainment, Education, Subscriptions, Other. Set "suggested_category" and "category_confidence" (0.0-1.0). If unsure, use "Other" with low confidence.
13. MULTI-SECTION STATEMENTS: a statement may contain more than one transaction section (e.g. "SAVINGS - TRANSACTION DETAILS" and "INVESTMENTS - TRANSACTION DETAILS"). Extract transactions from EVERY section, but record each cash movement EXACTLY ONCE. A transfer or fund purchase/redemption between the user's own accounts (e.g. "Buy - Mari Invest" / "Sell - Mari Invest") is shown as a cash movement in one section AND mirrored in another - include ONLY the single cash leg that moves THIS statement's balance (a purchase/"Buy" reduces cash -> OUT; a redemption/"Sell" adds cash -> IN), and do NOT also add the mirrored row from the other section as a second transaction. Do NOT skip transfers between the user's own accounts, and do NOT double-count them.
14. COMPLETENESS SELF-CHECK (do this before returning): reconcile EACH currency separately. For every currency present, opening_balance + sum(IN) - sum(OUT) for that currency MUST equal that currency's closing balance within 0.10. Never add amounts across different currencies. The top-level opening_balance/closing_balance are for the statement's primary currency. If a currency does NOT balance, you have either missed, duplicated, or mis-signed a transaction: use the running balance ("balance_after" / the daily balance column) to locate the day where the balance jumps and correct it using ONLY what the document actually shows. NEVER invent, fabricate, or alter transactions or balances to force a match - if the document genuinely does not reconcile, return exactly what is shown.
15. FOREIGN-EXCHANGE / CROSS-CURRENCY: if a line converts one currency to another (e.g. "Converted 1,000 SGD to 740 USD"), record the leg in the currency that actually moved on THIS statement and set its "currency" accordingly; preserve the other currency, the exchange rate, and any fee/spread in "raw_text" (and "reference" if shown). List a separately-shown fee as its own transaction.
"""

# Brokerage POSITIONS output schema (issue #1139 / #1088).
#
# A brokerage/securities statement's primary value is the holdings TABLE (the
# point-in-time positions), not a running-balance cash chain. The bank SYSTEM_PROMPT
# has NO positions field, so a brokerage doc routed through it loses every holding.
# This prompt fragment adds a top-level ``positions[]`` array whose item shape is
# exactly what ``brokerage_positions._iter_structured_positions`` /
# ``_parse_structured_positions`` already consume (``symbol``/``asset_identifier``,
# ``quantity``, ``market_value``, optional ``price``/``currency``/``asset_type``), so
# the producer side finally emits what the long-existing consumer side expects.
#
# Scope (#1139): this PR emits scalar ``market_value`` per position. A per-currency
# NAV / balance array is deliberately deferred to issue #1123 and intentionally NOT
# added here, to avoid colliding with that parallel slice.
BROKERAGE_POSITIONS_PROMPT = """You are a brokerage / securities statement parser.
Extract the point-in-time HOLDINGS (positions) table from the provided document.

PRIVACY INSTRUCTIONS:
- Do NOT extract or include any personally identifiable information (PII)
- Ignore names, addresses, NRIC/ID numbers, and full account numbers
- Only extract account_last4: the LAST 4 alphanumeric characters of the account number
- Focus only on financial holdings/position data

CRITICAL: Return a SINGLE JSON object (not an array).
Do NOT wrap the JSON in markdown or code fences.
Do NOT include any extra text before or after the JSON.

Output format (JSON object - NOT an array):
{
  "institution": "Broker Name",
  "account_last4": "1234",
  "currency": "USD",
  "snapshot_date": "2025-04-30",
  "period_start": "2025-04-01",
  "period_end": "2025-04-30",
  "positions": [
    {
      "symbol": "AAPL",
      "asset_identifier": "AAPL",
      "isin": "US0378331005",
      "quantity": "10",
      "price": "190.025",
      "market_value": "1900.25",
      "currency": "USD",
      "asset_type": "stock",
      "sector": "Technology",
      "geography": "US"
    }
  ],
  "transactions": []
}

Important Rules:
1. Output MUST be a single JSON object starting with `{`, NOT an array `[`, and no markdown
2. Extract EVERY row of the holdings/positions table - do NOT truncate
3. For each position emit at least an identifier (`symbol`/`ticker`/`isin`/`asset_identifier`),
   a `quantity`, and a `market_value`. Optionally include the closing `price` per unit and the
   position `currency`, `asset_type`, `sector`, and `geography` when the document shows them.
4. All amounts/quantities as non-negative strings, no thousands separators (e.g. "1900.25", "10")
5. Normalize EVERY date to ISO YYYY-MM-DD (convert from the source format yourself)
6. `snapshot_date` is the as-of date of the holdings (usually the statement period end)
7. asset_type: one of stock, etf, mutual_fund, money_market, bond, crypto, other (lowercase)
8. If the document ALSO shows cash activity rows (trades, dividends, fees), include them in
   `transactions` using the bank transaction shape; positions remain the primary output.
9. If NO holdings/positions table is present, return an EMPTY `positions` array (do not invent rows)
10. Auto-detect the broker name from the document header/logo into the "institution" field
"""


VALIDATION_PROMPT = """Verify the extracted data:

1. Balance check: opening_balance + sum(IN) - sum(OUT) ≈ closing_balance (tolerance: 0.10), computed per currency - never sum amounts across different currencies. Only perform a per-currency balance check when the document actually provides that currency's opening and closing balance.
2. Date check: All transaction dates should be within period_start and period_end
3. Completeness: No missing required fields

Return JSON only, no markdown or extra text:
{
  "balance_valid": true/false,
  "expected_closing": "12500.00",
  "actual_closing": "12500.00",
  "difference": "0.00",
  "date_issues": [],
  "missing_fields": [],
  "confidence_score": 85,
  "notes": "Optional explanation"
}
"""

# Institution-specific hints
INSTITUTION_HINTS = {
    "DBS": """
DBS Bank Singapore statement format:
- Header shows account number (last 4 digits after masking)
- Opening/Closing balance at top
- Transactions in date order: DD MMM YYYY format
- Credits marked "CR", debits have no suffix
- Look for "FAST", "PayNow", "GIRO" transaction types
""",
    "Moomoo": """
Moomoo brokerage statement format:
- CSV with headers: Date, Type, Symbol, Quantity, Price, Amount
- Transaction types: DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND, FEE
- Look for currency column (SGD/USD/HKD)
- Amounts already signed (negative for outflows)
- For generated Moomoo PDF fixtures, a Transaction Details row with Type
  SUBSCRIPTION and Description "Fullerton SGD Money Market Fund" represents a
  money-market holding; emit it as a position with asset_identifier/symbol
  "Fullerton SGD Money Market Fund", quantity "1", market_value equal to the row
  Amount, and currency equal to the row Currency. Do not return empty positions
  when this row is present.
""",
    "Futu": """
Futu/富途 brokerage statement format:
- Monthly statement PDF
- Account number in header
- Opening/Closing balance in the statement currency; do not assume HKD because
  generated fixtures and some real statements may use SGD or USD rows.
- Transactions may include: 股息 (dividends), 入金 (deposit), 出金 (withdrawal)
- Return a SINGLE JSON object, not an array
- For generated Futu PDF fixtures, a Transaction Details row with Type VALUATION
  and Description "Stock and options valuation" represents the point-in-time
  brokerage position; emit it as a position with asset_identifier/symbol
  "FUTU_STOCK_AND_OPTIONS", quantity "1", market_value equal to the row Amount,
  and currency equal to the row Currency. Do not return empty positions when this
  row is present.
""",
    "CMB": """
China Merchants Bank (招商银行) statement:
- PDF in Chinese
- 交易日期 = Transaction date
- 交易金额 = Amount (positive=credit, negative=debit)
- 账户余额 = Running balance
- Look for 工资/Salary, 转账/Transfer keywords
- May have many transactions (50-200+), include ALL of them
""",
    "Maybank": """
Maybank statement:
- PDF format with transaction table
- Look for \"Balance B/F\" and \"Balance C/F\"
- Amounts may include commas, remove them
""",
    "Wise": """
Wise statement/export:
- Multi-currency transactions
- Direction indicated by +/- or \"in\"/\"out\" labels
- Use the transaction currency when available
""",
    "Brokerage": """
Generic brokerage statement:
- Activity or transaction summary tables
- Common columns: Date, Type, Amount, Currency, Description
""",
    "Insurance": """
Insurance statement:
- Premium payments and policy charges
- Statement period and policy number in header
""",
    "IBKR": """
Interactive Brokers statement:
- Activity Statement format
- Multiple sections: Trades, Deposits/Withdrawals, Dividends
- Base currency conversion shown
- Net Asset Value at top
""",
    "GXS": """
GXS Bank Singapore statement:
- Digital bank monthly statement
- Daily interest transactions
- PayNow and GrabPay transfers
- Interest Earned entries
""",
    "MariBank": """
MariBank Singapore statement:
- Digital bank monthly statement
- Sections: SAVINGS transaction details, INVESTMENTS transaction details, and a daily SAVINGS interest-details table
- PayNow transfers to merchants
- Interest: a single total "Interest" line appears in the savings transaction table. The daily interest-details table is informational - do NOT also add each day as a separate transaction.
- Credit card repayments
- Fund transfers with Mari Invest: "Buy - Mari Invest" (cash OUT of savings) and "Sell - Mari Invest" (cash IN to savings) - always include these savings-side cash legs
""",
}


def get_parsing_prompt(
    institution: str | None = None,
    correction_examples: list[dict] | None = None,
    *,
    document_kind: str = "bank",
) -> str:
    """Get the full parsing prompt with institution-specific hints and few-shot corrections.

    Args:
        institution: Optional institution name for specific parsing hints.
        correction_examples: Optional list of user correction dicts with keys:
            - description: transaction description
            - original_category: AI's wrong suggestion
            - corrected_category: user's correction
        document_kind: ``"bank"`` (default) uses the bank ``SYSTEM_PROMPT`` whose
            schema is balance/transaction-only. ``"brokerage"`` selects
            ``BROKERAGE_POSITIONS_PROMPT`` so the model emits a ``positions[]``
            holdings array (issue #1139 producer routing). The brokerage path is
            chosen *before* the model call by the extraction service's brokerage
            classifier (filename/institution/broker-name keywords). The bank prompt
            is left unchanged for bank documents.
    """
    base_prompt = BROKERAGE_POSITIONS_PROMPT if document_kind == "brokerage" else SYSTEM_PROMPT
    prompt = base_prompt
    if institution:
        inst_upper = institution.upper()
        # Try exact match first, then partial match
        for key, hint in INSTITUTION_HINTS.items():
            if key.upper() == inst_upper:
                prompt += f"\n\nInstitution-specific guidance for {institution}:\n"
                prompt += hint
                break

    # EPIC-018 Phase 2: Inject few-shot correction examples
    if correction_examples:
        prompt += "\n\nIMPORTANT - Learn from these past categorization corrections:"
        prompt += "\nThe user has corrected these categories before. Use them to improve accuracy:\n"
        for ex in correction_examples:
            desc = ex.get("description", "")
            original = ex.get("original_category", "Other")
            corrected = ex.get("corrected_category", "")
            if desc and corrected:
                prompt += f'- "{desc}" → was "{original}", should be "{corrected}"\n'

    return prompt
