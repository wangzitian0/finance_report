# PDF Fixtures

> **SSOT Key**: `pdf_fixtures`
> **Source of Truth** for synthetic PDF fixture commands, local-only real-PDF
> handling, committed template policy, and font fallback.

PDF fixture tooling generates synthetic bank and brokerage statements for
parsing, reconciliation, portfolio, report-package, and E2E tests. Real
statements are local inputs only; committed files contain code, fictional data,
and format metadata.

## Tool Layout

| Path | Role |
|---|---|
| `tools/generate_pdf_fixtures.py` | Command wrapper for fixture generation |
| `tools/analyze_pdf_fixture.py` | Command wrapper for local real-PDF analysis |
| `tools/_lib/pdf_fixtures/generate_pdf_fixtures.py` | Shared generation implementation |
| `tools/_lib/pdf_fixtures/analyzers/` | PDF format analysis and sanitized template extraction |
| `tools/_lib/pdf_fixtures/generators/` | Source-specific PDF generators |
| `tools/_lib/pdf_fixtures/templates/*.yaml` | Committed format templates |
| `tools/_lib/pdf_fixtures/data/fake_data.py` | Fictional transaction data |
| `tools/_lib/pdf_fixtures/validators/pdf_validator.py` | Local structure validation |
| `tools/_lib/pdf_fixtures/input/` | Local real PDFs; gitignored |
| `tools/_lib/pdf_fixtures/output/` | Generated PDFs; gitignored |

## Generate Test PDFs

```bash
python tools/generate_pdf_fixtures.py --source all
python tools/generate_pdf_fixtures.py --source dbs
python tools/generate_pdf_fixtures.py --source cmb
python tools/generate_pdf_fixtures.py --source mari
python tools/generate_pdf_fixtures.py --source moomoo
python tools/generate_pdf_fixtures.py --source futu
python tools/generate_pdf_fixtures.py --source pingan
python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/
```

Default output is
`tools/_lib/pdf_fixtures/output/{source}/test_{source}_{period}.pdf`.

## Analyze Real PDFs

Real bank or brokerage PDFs may contain sensitive data. Keep them under
`tools/_lib/pdf_fixtures/input/`, which is gitignored and local only.

```bash
python tools/analyze_pdf_fixture.py \
  --input tools/_lib/pdf_fixtures/input/real_dbs_statement.pdf \
  --output tools/_lib/pdf_fixtures/templates/dbs_template.yaml \
  --source dbs
```

Review generated YAML before committing. Templates may include page size,
margins, font metadata, table columns, column widths, alignment, and text
element positions. Templates must not include account numbers, customer names,
real transaction payloads, or real balances.

## Commit Policy

Can be committed:

- `tools/_lib/pdf_fixtures/templates/*.yaml`
- analyzer, generator, validator, fake-data, and wrapper code
- thin local README files that point here

Cannot be committed:

- real PDFs under `input/`
- generated PDFs under `output/`, unless a future AC explicitly changes that
  policy
- copied sensitive values from real statements

## Font Fallback

`tools/_lib/pdf_fixtures/generators/font_utils.py` owns non-English font
handling:

- `register_chinese_fonts()` detects and registers available CJK fonts.
- `get_safe_font()` falls back to Helvetica when a requested font is missing.
- `can_display_chinese()` checks whether registered fonts can render CJK text.

Known search paths include macOS system CJK fonts, Linux WQY/AR PL fonts, and
Windows SimSun/SimHei fonts. CMB and Pingan generators use Chinese headers when
supported and fall back to English text when no suitable font is available.
Fictional transaction descriptions stay English to keep generated PDFs portable.

Quick check:

```bash
python -c "from tools._lib.pdf_fixtures.generators.font_utils import register_chinese_fonts; print(register_chinese_fonts())"
```

The command prints a registered font name such as `ChineseFont`, or `None` when
the platform must use fallback text.

## Proof

| Contract | Proof owner |
|---|---|
| AC definitions | [EPIC-009](../project/EPIC-009.pdf-fixture-generation.md) |
| Analyzer, sanitizer, templates, generator registration, gitignore, and docs | `tests/tooling/test_pdf_fixture_epic009_behavior.py` |
| Source-specific generated PDFs, dates, and balances | `tests/tooling/test_pdf_fixture_parseable.py` |
| CLI branches and validator behavior | `tests/tooling/test_pdf_fixture_tooling_coverage.py` |
| E2E consumers | `tests/e2e/test_statement_full_journey.py`, `tests/e2e/test_brokerage_upload_to_portfolio_value.py`, `tests/e2e/test_four_asset_net_worth_golden_path.py`, `tests/e2e/test_personal_financial_report_package.py` |
