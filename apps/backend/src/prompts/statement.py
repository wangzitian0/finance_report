"""Prompt templates for statement parsing."""

SYSTEM_PROMPT = """You are a financial statement parser.
Extract structured transaction data from the provided document.

CRITICAL: Return a SINGLE JSON object (not an array).
Even if the document contains multiple accounts, combine them into one response.

Output format (JSON object - NOT an array):
{
  "institution": "Bank Name",
  "account_last4": "1234",
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
      "raw_text": "15 Jan SALARY ACME CORP 5,000.00 CR"
    }
  ]
}

Important Rules:
1. Output MUST be a single JSON object starting with `{`, NOT an array `[`
2. All amounts as strings with 2 decimal places, no commas (e.g., "10000.00")
3. Dates in YYYY-MM-DD format
4. direction: "IN" for credits/deposits, "OUT" for debits/withdrawals
5. Include ALL transactions visible in the document
6. Preserve raw_text exactly as shown (for audit trail)
7. If unsure about a field, set it to null but include the transaction
8. For long statements with 50+ transactions, include all of them - do NOT truncate
"""

VALIDATION_PROMPT = """Verify the extracted data:

1. Balance check: opening_balance + sum(IN) - sum(OUT) ≈ closing_balance (tolerance: 0.10)
2. Date check: All transaction dates should be within period_start and period_end
3. Completeness: No missing required fields

Return JSON:
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
""",
    "Futu": """
Futu/富途 brokerage statement format (HKD account):
- Monthly statement PDF
- Account number in header
- Opening/Closing balance in HKD
- Transactions may include: 股息 (dividends), 入金 (deposit), 出金 (withdrawal)
- Return a SINGLE JSON object, not an array
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
- PayNow transfers to merchants
- Interest entries
- Credit card repayments
""",
}


def get_parsing_prompt(institution: str | None = None) -> str:
    """Get the full parsing prompt with institution-specific hints."""
    prompt = SYSTEM_PROMPT
    if institution:
        inst_upper = institution.upper()
        # Try exact match first, then partial match
        for key, hint in INSTITUTION_HINTS.items():
            if key.upper() == inst_upper:
                prompt += f"\n\nInstitution-specific guidance for {institution}:\n"
                prompt += hint
                break
    return prompt
