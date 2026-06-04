# EPIC-009: PDF Fixture Generation for Testing

> **Status**: ✅ Complete  
> **Vision Anchor**: `decision-filter-accuracy-auditability`  
> **Phase**: 2  
> **Duration**: 2-3 weeks  
> **Dependencies**: EPIC-003 (Statement Parsing), EPIC-008 (Testing Strategy)

---

## 🎯 Objective

Create an **offline tool** to generate synthetic PDF bank statements that match the format of real PDFs from different sources (DBS, CMB, Mari Bank, etc.). These fixtures will be used for:
- **E2E Testing**: Validating the upload → parse → reconcile pipeline
- **Unit Testing**: Testing adapters with known, deterministic data
- **Regression Testing**: Ensuring format changes don't break parsing

**Key Requirements:**
- Format must match real PDFs (layout, fonts, table structure)
- Use fictional data (no PII)
- Real PDFs stay offline (not committed to repo)
- Format templates and generation code can be committed

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Tool Design | Offline analysis → template → generation workflow ensures format consistency |
| 💻 **Developer** | Implementation | pdfplumber for analysis, reportlab for generation, YAML templates for format |
| 🧪 **Tester** | Test Coverage | Generated PDFs must be parseable by adapters, format must match real PDFs |
| 📋 **PM** | Usability | Other developers can generate test PDFs without access to real PDFs |
| 🔗 **Reconciler** | Data Quality | Generated transactions must have correct balance calculations |

---

## Source of Truth Ownership

This EPIC owns the AC9.x requirement IDs. Implementation detail, command usage,
template shape, and live proof are intentionally code-owned to avoid another
hand-maintained project checklist.

| Fact | Owner |
|---|---|
| PDF fixture CLI usage and generated-output policy | [PDF fixture README](https://github.com/wangzitian0/finance_report/blob/main/tools/_lib/pdf_fixtures/README.md) |
| Font fallback behavior | [PDF fixture font handling](https://github.com/wangzitian0/finance_report/blob/main/tools/_lib/pdf_fixtures/FONT_HANDLING.md) |
| Analyzer and template extraction behavior | `tools/_lib/pdf_fixtures/analyzers/`, `tools/analyze_pdf_fixture.py` |
| Generator, validator, and fake-data behavior | `tools/_lib/pdf_fixtures/`, `tools/generate_pdf_fixtures.py` |
| Parseability, date-format, balance, and template contracts | `tests/tooling/test_pdf_fixture_*.py` |
| Real PDF exclusion and sensitive-output policy | `.gitignore`, `tools/_lib/pdf_fixtures/README.md` |

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `tools/_lib/pdf_fixtures/` and template files

### AC9.1: PDF Format Analysis (Phase 0)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.1.1 | PDF analyzer exists | Manual verification | `tools/_lib/pdf_fixtures/analyzers/pdf_analyzer.py` | P0 |
| AC9.1.2 | Template extractor exists | Manual verification | `tools/_lib/pdf_fixtures/analyzers/template_extractor.py` | P0 |
| AC9.1.3 | CLI tool exists | Manual verification | `tools/analyze_pdf_fixture.py` | P0 |
| AC9.1.4 | DBS template exists | Manual verification | `tools/_lib/pdf_fixtures/templates/dbs_template.yaml` | P0 |
| AC9.1.5 | CMB template exists | Manual verification | `tools/_lib/pdf_fixtures/templates/cmb_template.yaml` | P0 |
| AC9.1.6 | Mari Bank template exists | Manual verification | `tools/_lib/pdf_fixtures/templates/mari_template.yaml` | P0 |

### AC9.2: PDF Generators (Phase 1)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.2.1 | Base generator class exists | Manual verification | `tools/_lib/pdf_fixtures/generators/base_generator.py` | P0 |
| AC9.2.2 | DBS generator exists | Manual verification | `tools/_lib/pdf_fixtures/generators/dbs_generator.py` | P0 |
| AC9.2.3 | CMB generator exists | Manual verification | `tools/_lib/pdf_fixtures/generators/cmb_generator.py` | P0 |
| AC9.2.4 | Mari Bank generator exists | Manual verification | `tools/_lib/pdf_fixtures/generators/mari_generator.py` | P0 |
| AC9.2.5 | Font utilities exist | Manual verification | `tools/_lib/pdf_fixtures/generators/font_utils.py` | P0 |
| AC9.2.6 | Fake data generator exists | Manual verification | `tools/_lib/pdf_fixtures/data/fake_data.py` | P0 |
| AC9.2.7 | Main script exists | Manual verification | `tools/generate_pdf_fixtures.py` | P0 |

### AC9.3: PDF Validation (Phase 2)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.3.1 | Format validator exists | Manual verification | `tools/_lib/pdf_fixtures/validators/pdf_validator.py` | P0 |
| AC9.3.2 | Generated DBS PDF parseable | `test_ac9_3_2_dbs_generated_pdf_parseable` | `tests/tooling/test_pdf_fixture_parseable.py` | P0 |
| AC9.3.3 | Generated CMB PDF parseable | `test_ac9_3_3_cmb_generated_pdf_parseable` | `tests/tooling/test_pdf_fixture_parseable.py` | P0 |
| AC9.3.4 | Generated Mari PDF parseable | `test_ac9_3_4_mari_generated_pdf_parseable` | `tests/tooling/test_pdf_fixture_parseable.py` | P0 |
| AC9.3.5 | Balance calculations correct | `test_ac9_3_5_balance_calculations_correct` | `tests/tooling/test_pdf_fixture_parseable.py` | P0 |
| AC9.3.6 | Date formats correct | `test_ac9_3_6_date_formats_correct_per_source` | `tests/tooling/test_pdf_fixture_parseable.py` | P0 |

### AC9.4: Documentation & Integration (Phase 3)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.4.1 | Format analysis README | Manual verification | `tools/_lib/pdf_fixtures/analyzers/README.md` | P0 |
| AC9.4.2 | Generation README | Manual verification | `tools/_lib/pdf_fixtures/README.md` | P0 |
| AC9.4.3 | Template format specification | Manual verification | README documentation | P0 |
| AC9.4.4 | Usage examples | Manual verification | README documentation | P0 |

### AC9.5: Git Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.5.1 | .gitignore excludes real PDFs | Manual verification | `.gitignore` | P0 |
| AC9.5.2 | Format templates committed | Manual verification | Git check | P0 |
| AC9.5.3 | Generators committed | Manual verification | Git check | P0 |
| AC9.5.4 | Analyzers committed | Manual verification | Git check | P0 |
| AC9.5.5 | Validators committed | Manual verification | Git check | P0 |

### AC9.6: Generator Implementation Quality

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.6.1 | DBS generator loads template | Manual verification | `dbs_generator.py` code review | P0 |
| AC9.6.2 | CMB generator loads template | Manual verification | `cmb_generator.py` code review | P0 |
| AC9.6.3 | CMB generator supports Chinese fonts | Manual verification | `font_utils.py` code review | P0 |
| AC9.6.4 | Mari generator generates interest section | Manual verification | `mari_generator.py` code review | P0 |
| AC9.6.5 | Generators use fictional data | Manual verification | `fake_data.py` code review | P0 |

### AC9.7: CLI & Script Functionality

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.7.1 | Main script supports --source parameter | Manual verification | `generate_pdf_fixtures.py` usage | P0 |
| AC9.7.2 | Main script supports --output parameter | Manual verification | `generate_pdf_fixtures.py` usage | P0 |
| AC9.7.3 | Analyzer CLI supports input/output | Manual verification | `analyze_pdf.py` usage | P0 |

*(AC9.8.x section removed — these were intra-EPIC summary duplicates of AC9.3.x, AC9.5.x, AC9.6.x, and AC9.7.x)*
## 📚 References

- EPIC-003: Statement Parsing (uses generated PDFs)
- EPIC-008: Testing Strategy (mentions PDF fixtures)
- Existing: `tools/generate_pdf_fixtures.py`
- Adapters: `wealth_pipeline2/src/adapters/` (DBS, CMB, Mari Bank)

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [PDF fixture README](https://github.com/wangzitian0/finance_report/blob/main/tools/_lib/pdf_fixtures/README.md) — PDF fixture tool usage.
- [PDF fixture font handling](https://github.com/wangzitian0/finance_report/blob/main/tools/_lib/pdf_fixtures/FONT_HANDLING.md) — fixture font fallback behavior.
