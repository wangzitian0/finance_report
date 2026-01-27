# EPIC-009: PDF Fixture Generation — GENERATED

> **Auto-generated implementation summary** — Do not edit manually.
> **Last updated**: 2026-01-27
> **Source EPIC**: [EPIC-009.pdf-fixture-generation.md](./EPIC-009.pdf-fixture-generation.md)

---

## 📋 Implementation Summary

EPIC-009 provides an offline tool to generate synthetic PDF bank statements for testing purposes. The tool supports multiple bank formats (DBS, CMB, Mari Bank) and produces deterministic, parseable PDFs with fictional data.

### Purpose

- **E2E Testing**: Validate upload → parse → reconcile pipeline
- **Unit Testing**: Test adapters with known, deterministic data
- **Regression Testing**: Ensure format changes don't break parsing

### Completed Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| PDF Analyzer | `scripts/analyzers/pdf_analyzer.py` | ✅ Complete |
| Template Extractor | `scripts/analyzers/template_extractor.py` | ✅ Complete |
| Analyze PDF CLI | `scripts/analyzers/analyze_pdf.py` | ✅ Complete |
| DBS Template | `scripts/templates/dbs_template.yaml` | ✅ Complete |
| CMB Template | `scripts/templates/cmb_template.yaml` | ✅ Complete |
| Mari Bank Template | `scripts/templates/mari_template.yaml` | ✅ Complete |
| Base Generator | `scripts/generators/base_generator.py` | ✅ Complete |
| DBS Generator | `scripts/generators/dbs_generator.py` | ✅ Complete |
| CMB Generator | `scripts/generators/cmb_generator.py` | ✅ Complete |
| Mari Bank Generator | `scripts/generators/mari_generator.py` | ✅ Complete |
| Fake Data Generator | `scripts/data/fake_data.py` | ✅ Complete |
| Main Script | `scripts/generate_pdf_fixtures.py` | ✅ Complete |
| Format Validator | `scripts/validators/pdf_validator.py` | ✅ Complete |
| Documentation | `scripts/README.md` | ✅ Complete |

---

## 🏗️ Architecture

### Workflow Overview

```
Phase 0: Format Analysis (Local, Offline)
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Real PDF       │ --> │   PDF Analyzer   │ --> │  Format Template │
│ (not committed)  │     │   (pdfplumber)   │     │   (YAML file)    │
└──────────────────┘     └──────────────────┘     └──────────────────┘

Phase 1: PDF Generation (Committed Code)
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Format Template  │ --> │   PDF Generator  │ --> │   Test PDF       │
│   (YAML file)    │     │   (reportlab)    │     │ (fictional data) │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Directory Structure

```
scripts/
├── generate_pdf_fixtures.py      # Main entry point
├── README.md                      # Usage documentation
├── analyzers/
│   ├── __init__.py
│   ├── pdf_analyzer.py            # Extract format from real PDFs
│   ├── template_extractor.py      # Convert to YAML format
│   └── analyze_pdf.py             # CLI tool
├── generators/
│   ├── __init__.py
│   ├── base_generator.py          # Common PDF utilities
│   ├── dbs_generator.py           # DBS format
│   ├── cmb_generator.py           # CMB format (Chinese)
│   └── mari_generator.py          # Mari Bank format
├── templates/
│   ├── dbs_template.yaml          # ✅ Committed
│   ├── cmb_template.yaml          # ✅ Committed
│   └── mari_template.yaml         # ✅ Committed
├── data/
│   └── fake_data.py               # Fictional transaction generator
└── validators/
    └── pdf_validator.py           # Format validation
```

---

## 📝 Usage

### Generate Test PDFs

```bash
# Generate all bank formats
python scripts/generate_pdf_fixtures.py --source all --output tmp/fixtures/

# Generate specific bank format
python scripts/generate_pdf_fixtures.py --source dbs --output tmp/fixtures/

# Generate with custom date range
python scripts/generate_pdf_fixtures.py --source cmb \
  --output tmp/fixtures/ \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

### Analyze Real PDF (Local Only)

```bash
# Extract format template from real PDF
python scripts/analyzers/analyze_pdf.py \
  --input ~/private/bank_statements/dbs_2501.pdf \
  --output scripts/templates/dbs_template.yaml

# Verify template contains no PII
cat scripts/templates/dbs_template.yaml | grep -i "account\|balance\|name"
```

### Validate Generated PDF

```bash
# Validate format matches template
python scripts/validators/pdf_validator.py \
  --pdf tmp/fixtures/dbs/test_dbs_2501.pdf \
  --template scripts/templates/dbs_template.yaml
```

---

## 📋 Format Template Structure

### Example: `dbs_template.yaml`

```yaml
# Page configuration
page:
  size: A4
  margins:
    top: 72
    bottom: 72
    left: 72
    right: 72

# Font definitions
fonts:
  header:
    family: Helvetica-Bold
    size: 14
  body:
    family: Helvetica
    size: 10
  table_header:
    family: Helvetica-Bold
    size: 9

# Table structure
table:
  transaction_details:
    columns:
      - name: Date
        width: 70
        align: left
        format: DD/MM/YYYY
      - name: Description
        width: 200
        align: left
      - name: Withdrawal
        width: 60
        align: right
        format: currency
      - name: Deposit
        width: 60
        align: right
        format: currency
      - name: Balance
        width: 70
        align: right
        format: currency
    header_style:
      background: "#CCCCCC"
      text_color: "#000000"
    row_style:
      background: "#FFFFFF"
      border: "1px solid #000000"

# Sections
sections:
  - type: header
    content: "DBS Bank Statement"
  - type: account_info
    fields: [account_number, statement_period]
  - type: table
    id: transaction_details
  - type: summary
    fields: [opening_balance, closing_balance]
```

### Supported Banks

| Bank | Template | Date Format | Currency | Chinese Fonts |
|------|----------|-------------|----------|---------------|
| DBS | `dbs_template.yaml` | DD/MM/YYYY | SGD | No |
| CMB | `cmb_template.yaml` | YYYY-MM-DD | CNY | Yes (宋体, 黑体) |
| Mari Bank | `mari_template.yaml` | DD MMM | SGD | No |

---

## 🔒 Security & Git Configuration

### What CAN be Committed

| File Type | Example | Reason |
|-----------|---------|--------|
| Format templates | `scripts/templates/*.yaml` | Only format parameters, no data |
| Generator code | `scripts/generators/*.py` | Code, no data |
| Analyzer code | `scripts/analyzers/*.py` | Code, no data |
| Generated test PDFs | `tmp/fixtures/*.pdf` | Fictional data |
| Fake data generator | `scripts/data/fake_data.py` | Generates fake data |

### What CANNOT be Committed

| File Type | Example | Reason |
|-----------|---------|--------|
| Real PDF files | `*.real.pdf` | Contains PII |
| Analysis outputs | `*.analysis.json` | May contain sensitive data |
| Sensitive PDFs | `wealth_pipeline/input/**/*.pdf` | Real bank statements |

### .gitignore Additions

```gitignore
# Real PDFs (sensitive, don't commit)
wealth_pipeline/input/**/*.pdf
wealth_pipeline/input/**/*.PDF
*.real.pdf
*.sensitive.pdf

# Local analysis outputs (if contain sensitive info)
*.analysis.json
*.analysis.yaml
!scripts/templates/*.yaml  # Allow committed templates
```

---

## 🧪 Testing Status

### Phase 0: Format Analysis

| Task | Status | Notes |
|------|--------|-------|
| PDF Analyzer | ✅ Complete | Uses pdfplumber |
| Template Extractor | ✅ Complete | Outputs YAML |
| DBS Template | ✅ Complete | From adapter code analysis |
| CMB Template | ✅ Complete | From adapter code analysis |
| Mari Template | ✅ Complete | From adapter code analysis |
| Manual verification | ⏳ Pending | Requires real PDF access |

### Phase 1: PDF Generation

| Task | Status | Notes |
|------|--------|-------|
| Base Generator | ✅ Complete | reportlab-based |
| DBS Generator | ✅ Complete | SGD format |
| CMB Generator | ✅ Complete | Chinese fonts |
| Mari Generator | ✅ Complete | SGD format |
| Fake Data Generator | ✅ Complete | Deterministic |
| Main Script | ✅ Complete | CLI interface |

### Phase 2: Validation & Testing

| Task | Status | Notes |
|------|--------|-------|
| Format Validator | ✅ Complete | Structure comparison |
| DBS Adapter Test | ⏳ Pending | Integration test |
| CMB Adapter Test | ⏳ Pending | Integration test |
| Mari Adapter Test | ⏳ Pending | Integration test |
| Visual Comparison | ⏳ Pending | Manual, local only |

### Phase 3: Documentation & Integration

| Task | Status | Notes |
|------|--------|-------|
| README | ✅ Complete | Usage examples |
| CI Integration | ⏳ Pending | Generate in CI |
| Git Configuration | ✅ Complete | .gitignore updated |

---

## 📏 Acceptance Criteria Status

### 🟢 Must Have

| Criterion | Status | Verification |
|-----------|--------|--------------|
| Analyzer extracts template | ⏳ | Run on real PDF |
| Template contains no PII | ✅ | Review YAML files |
| DBS PDF parseable | ⏳ | Run adapter test |
| CMB PDF parseable | ⏳ | Run adapter test |
| Mari PDF parseable | ⏳ | Run adapter test |
| Balance calculations correct | ✅ | Opening + Txns = Closing |
| Date formats match | ✅ | DBS: DD/MM/YYYY, CMB: YYYY-MM-DD |
| Fictional data only | ✅ | Review generated PDFs |
| Templates committed | ✅ | In `scripts/templates/` |
| Real PDFs excluded | ✅ | .gitignore configured |

---

## 🔗 References

- [EPIC-003: Statement Parsing](./EPIC-003.statement-parsing.md) — Uses generated PDFs
- [EPIC-008: Testing Strategy](./EPIC-008.testing-strategy.md) — Mentions PDF fixtures
- Adapters: `wealth_pipeline2/src/adapters/` (DBS, CMB, Mari Bank)

---

## ✅ Verification Commands

```bash
# Generate test PDFs
python scripts/generate_pdf_fixtures.py --source all --output tmp/fixtures/

# Verify generated PDF structure
python scripts/validators/pdf_validator.py \
  --pdf tmp/fixtures/dbs/test_dbs_2501.pdf \
  --template scripts/templates/dbs_template.yaml

# Test adapter can parse generated PDF
moon run backend:test -- -k "test_dbs_adapter" -v

# Check no real PDFs in git
git status | grep -i ".pdf"
```

---

*This file is auto-generated from EPIC-009 implementation. For goals and acceptance criteria, see [EPIC-009.pdf-fixture-generation.md](./EPIC-009.pdf-fixture-generation.md).*
