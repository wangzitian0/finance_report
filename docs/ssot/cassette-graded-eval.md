
## Own (real) statements — committed only when strict-masked to zero PII

The corpus may also include the maintainer's REAL statements (real document layouts,
multi-currency, brokerage holdings — coverage synthetic data lacks). Because git is a
zero-PII red line, a real cassette is committed ONLY after STRICT masking: identity meta
and ALL free-text (`description`, `raw_text`, `reference`, …) are fully redacted to `**`
(`mask_extraction(..., strict=True)`) — `first3***last3` is NOT enough for a real name.
Only flow values (date/amount/direction/balance/currency) and public security symbols
remain. The extraction is produced locally (no third-party API), and the cassette stores
a `sha256` source reference — never the PDF/image.

`test_AC23_8_6` enforces this structurally for every committed cassette: it is either
`synthetic: true`, or `synthetic: false` AND proven PII-free here (no CJK character
survives; every identity/free-text field is `**`). Real single-currency bank statements
that genuinely reconcile stay balance-asserted (AC23.7); brokerage and multi-currency
cassettes are balance-exempt (`balance_reconciles: false`) and field-graded only.
