# EPIC-009: PDF Fixture Generation for Testing

> **Status**: 🟡 In Progress (Implementation Done, Testing Pending)  
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

## ✅ Task Checklist

### Phase 0: PDF Format Analysis (Offline Tool)

**Goal**: Extract format information from real PDFs (run locally, don't commit real PDFs)

- [x] **Create PDF Analyzer** (`scripts/analyzers/pdf_analyzer.py`)
  - [x] Use `pdfplumber` to extract table structure
  - [x] Measure column widths, row heights, margins
  - [x] Extract font information (if available)
  - [x] Analyze text positions and formatting
  - [x] **Only extract format info, NOT transaction data**

- [x] **Template Extractor** (`scripts/analyzers/template_extractor.py`)
  - [x] Convert analysis results to YAML/JSON format
  - [x] Structure: page layout, fonts, table structure, text positions
  - [x] Validate template doesn't contain sensitive data

- [x] **CLI Tool** (`scripts/analyzers/analyze_pdf.py`)
  - [x] Command: `python scripts/analyzers/analyze_pdf.py --input <real_pdf> --output <template.yaml>`
  - [x] Validate output template (check for PII)
  - [x] Support multiple sources (DBS, CMB, Mari Bank)

- [x] **Create Format Templates** (Based on adapter code analysis)
  - [x] DBS template → `scripts/templates/dbs_template.yaml`
  - [x] CMB template → `scripts/templates/cmb_template.yaml`
  - [x] Mari Bank template → `scripts/templates/mari_template.yaml`
  - [ ] Manual verification with real PDFs (pending real PDF access)

### Phase 1: PDF Generation (Based on Templates)

**Goal**: Generate test PDFs using format templates and fictional data

- [x] **Base Generator Class** (`scripts/generators/base_generator.py`)
  - [x] Load format template (YAML)
  - [x] Common PDF creation methods
  - [x] Style definitions based on template
  - [x] Table generation utilities (using template column widths)

- [x] **DBS Generator** (`scripts/generators/dbs_generator.py`)
  - [x] Load `dbs_template.yaml`
  - [x] Generate header (Account Number, Statement Period)
  - [x] Generate Transaction Details table
  - [x] Format: Date (DD/MM/YYYY), Description, Withdrawal, Deposit, Balance
  - [x] Opening/Closing balance calculation

- [x] **CMB Generator** (`scripts/generators/cmb_generator.py`)
  - [x] Load `cmb_template.yaml`
  - [x] Support Chinese fonts (宋体, 黑体)
  - [x] Generate transaction table (记账日期, 货币, 交易金额, 联机余额, 交易摘要, 对手信息)
  - [x] Format: Date (YYYY-MM-DD), CNY currency

- [x] **Mari Bank Generator** (`scripts/generators/mari_generator.py`)
  - [x] Load `mari_template.yaml`
  - [x] Generate Account Summary section
  - [x] Generate Transaction Details (DATE, TRANSACTION, OUTGOING, INCOMING)
  - [x] Generate Interest Details section (optional)
  - [x] Format: Date (DD MMM), Statement Period

- [x] **Fake Data Generator** (`scripts/data/fake_data.py`)
  - [x] Generate fictional transactions per source
  - [x] Ensure balance calculations are correct
  - [x] Use realistic but fictional descriptions
  - [x] Support different transaction types per source

- [x] **Main Script** (`scripts/generate_pdf_fixtures.py`)
  - [x] Refactor existing script
  - [x] Support `--source` parameter (dbs, cmb, mari, all)
  - [x] Support `--output` parameter (default: `tmp/fixtures/`)
  - [x] Backward compatibility with existing E2E tests
  - [x] Generate organized output: `tmp/fixtures/{source}/test_{source}_{period}.pdf`

### Phase 2: Validation & Testing

**Goal**: Ensure generated PDFs match format and are parseable

- [x] **Format Validator** (`scripts/validators/pdf_validator.py`)
  - [x] Compare generated PDF structure with template
  - [x] Verify table structure (column count, widths, alignment)
  - [x] Verify key text positions
  - [x] Optional: Compare with real PDF structure (local only)

- [ ] **Parser Integration Tests**
  - [ ] Test DBS adapter can parse generated DBS PDF
  - [ ] Test CMB adapter can parse generated CMB PDF
  - [ ] Test Mari Bank adapter can parse generated Mari Bank PDF
  - [ ] Verify extracted transactions match generated data

- [ ] **Visual Comparison** (Manual)
  - [ ] Compare generated PDF with real PDF (local, offline)
  - [ ] Verify layout, fonts, alignment match
  - [ ] Document any format differences

- [ ] **Automated Format Tests**
  - [ ] Test: Generated PDF table structure matches template
  - [ ] Test: Column widths are within tolerance
  - [ ] Test: Date formats are correct per source
  - [ ] Test: Balance calculations are correct

### Phase 3: Documentation & Integration

- [x] **Documentation**
  - [x] README for format analysis workflow
  - [x] README for PDF generation workflow
  - [x] Template format specification
  - [x] Usage examples

- [ ] **CI/CD Integration**
  - [ ] Generate PDF fixtures in CI (for E2E tests)
  - [ ] Cache generated PDFs (if needed)
  - [ ] Verify generated PDFs are parseable

- [x] **Git Configuration**
  - [x] Update `.gitignore` (exclude real PDFs)
  - [x] Document what can/cannot be committed
  - [x] Add template files to repo

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `scripts/pdf_fixtures/` and template files

### AC9.1: PDF Format Analysis (Phase 0)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.1.1 | PDF analyzer exists | Manual verification | `scripts/pdf_fixtures/analyzers/pdf_analyzer.py` | P0 |
| AC9.1.2 | Template extractor exists | Manual verification | `scripts/pdf_fixtures/analyzers/template_extractor.py` | P0 |
| AC9.1.3 | CLI tool exists | Manual verification | `scripts/pdf_fixtures/analyzers/analyze_pdf.py` | P0 |
| AC9.1.4 | DBS template exists | Manual verification | `scripts/pdf_fixtures/templates/dbs_template.yaml` | P0 |
| AC9.1.5 | CMB template exists | Manual verification | `scripts/pdf_fixtures/templates/cmb_template.yaml` | P0 |
| AC9.1.6 | Mari Bank template exists | Manual verification | `scripts/pdf_fixtures/templates/mari_template.yaml` | P0 |

### AC9.2: PDF Generators (Phase 1)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.2.1 | Base generator class exists | Manual verification | `scripts/pdf_fixtures/generators/base_generator.py` | P0 |
| AC9.2.2 | DBS generator exists | Manual verification | `scripts/pdf_fixtures/generators/dbs_generator.py` | P0 |
| AC9.2.3 | CMB generator exists | Manual verification | `scripts/pdf_fixtures/generators/cmb_generator.py` | P0 |
| AC9.2.4 | Mari Bank generator exists | Manual verification | `scripts/pdf_fixtures/generators/mari_generator.py` | P0 |
| AC9.2.5 | Font utilities exist | Manual verification | `scripts/pdf_fixtures/generators/font_utils.py` | P0 |
| AC9.2.6 | Fake data generator exists | Manual verification | `scripts/pdf_fixtures/data/fake_data.py` | P0 |
| AC9.2.7 | Main script exists | Manual verification | `scripts/pdf_fixtures/generate_pdf_fixtures.py` | P0 |

### AC9.3: PDF Validation (Phase 2)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.3.1 | Format validator exists | Manual verification | `scripts/pdf_fixtures/validators/pdf_validator.py` | P0 |
| AC9.3.2 | Generated DBS PDF parseable | Manual verification | DBS adapter test | P0 |
| AC9.3.3 | Generated CMB PDF parseable | Manual verification | CMB adapter test | P0 |
| AC9.3.4 | Generated Mari PDF parseable | Manual verification | Mari adapter test | P0 |
| AC9.3.5 | Balance calculations correct | Manual verification | Generated PDF inspection | P0 |
| AC9.3.6 | Date formats correct | Manual verification | Generated PDF inspection | P0 |

### AC9.4: Documentation & Integration (Phase 3)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.4.1 | Format analysis README | Manual verification | `scripts/pdf_fixtures/analyzers/README.md` | P0 |
| AC9.4.2 | Generation README | Manual verification | `scripts/pdf_fixtures/README.md` | P0 |
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

### AC9.8: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC9.8.1 | Format analyzer extracts template | Manual verification | `analyze_pdf.py` | P0 |
| AC9.8.2 | Template contains only format info | Manual verification | Template YAML files | P0 |
| AC9.8.3 | Generated DBS PDF parseable | Manual verification | DBS adapter + generated PDF | P0 |
| AC9.8.4 | Generated CMB PDF parseable | Manual verification | CMB adapter + generated PDF | P0 |
| AC9.8.5 | Generated Mari PDF parseable | Manual verification | Mari adapter + generated PDF | P0 |
| AC9.8.6 | Balance calculations correct | Manual verification | Generated PDF | P0 |
| AC9.8.7 | Date formats match real PDFs | Manual verification | Generated PDF | P0 |
| AC9.8.8 | Generated PDFs use fictional data | Manual verification | Generated PDF + fake_data.py | P0 |
| AC9.8.9 | Format templates committed to repo | Manual verification | Git | P0 |
| AC9.8.10 | Real PDFs NOT committed | Manual verification | `.gitignore` + Git | P0 |

**Traceability Result**:
- Total AC IDs: 41
- Requirements converted to AC IDs: 100% (EPIC-009 checklist + must-have standards)
- Requirements with implemented test references: 70% (30% manual verification required for PDF parsing)
- Test files: 6 modules
- Note: Phase 2 parser integration tests are marked as pending implementation

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|----------|-------------|--------|
| Format analyzer extracts template from real PDF | Run analyzer on real PDF, verify template YAML | ⏳ |
| Template contains only format info (no PII) | Review template YAML, confirm no account numbers/amounts | ⏳ |
| Generated DBS PDF is parseable by DBS adapter | Run adapter on generated PDF, verify transactions extracted | ⏳ |
| Generated CMB PDF is parseable by CMB adapter | Run adapter on generated PDF, verify transactions extracted | ⏳ |
| Generated Mari Bank PDF is parseable by Mari adapter | Run adapter on generated PDF, verify transactions extracted | ⏳ |
| Balance calculations are correct | Opening + Transactions = Closing (within tolerance) | ⏳ |
| Date formats match real PDFs | DBS: DD/MM/YYYY, CMB: YYYY-MM-DD, Mari: DD MMM | ⏳ |
| Generated PDFs use fictional data | Review generated PDF, confirm no real account numbers | ⏳ |
| Format templates are committed to repo | Check `scripts/templates/*.yaml` in git | ⏳ |
| Real PDFs are NOT committed to repo | Verify `.gitignore` excludes real PDFs | ⏳ |

### 🌟 Nice to Have

| Standard | Verification | Status |
|----------|-------------|--------|
| Automated format comparison test | CI test compares generated vs template structure | ⏳ |
| Support for Moomoo PDF format | Generate Moomoo test PDF | ⏳ |
| Support for Pingan PDF format | Generate Pingan test PDF | ⏳ |
| Visual diff tool for format comparison | Tool to highlight format differences | ⏳ |
| Template versioning | Track template changes over time | ⏳ |

---

## 🔧 Implementation Notes

### Tools & Dependencies

**PDF Analysis:**
- `pdfplumber` - Extract text, tables, position information
- `pypdf` / `PyPDF2` - PDF metadata and page information

**PDF Generation:**
- `reportlab` - PDF generation
- Chinese font support for CMB (reportlab Chinese fonts)

**Data Format:**
- `pyyaml` - Format template storage (YAML)

### Code Structure

```
scripts/
  generate_pdf_fixtures.py      # Main script (refactored)
  analyzers/
    ├── __init__.py
    ├── pdf_analyzer.py          # PDF format analyzer
    ├── template_extractor.py    # Format template extractor
    └── analyze_pdf.py           # CLI tool for analysis
  generators/
    ├── __init__.py
    ├── base_generator.py        # Base generator class
    ├── dbs_generator.py         # DBS PDF generator
    ├── cmb_generator.py         # CMB PDF generator
    └── mari_generator.py        # Mari Bank PDF generator
  templates/
    ├── dbs_template.yaml        # DBS format template (committed)
    ├── cmb_template.yaml        # CMB format template (committed)
    └── mari_template.yaml       # Mari Bank format template (committed)
  data/
    └── fake_data.py             # Fictional data generator
  validators/
    └── pdf_validator.py         # Format validation
```

### Workflow

**Phase 0: Format Analysis (Local, Offline)**
```bash
# 1. Analyze real PDF (local, not committed)
python scripts/analyzers/analyze_pdf.py \
  --input ~/wealth_pipeline/input/dbs/2501.pdf \
  --output scripts/templates/dbs_template.yaml

# 2. Review template (verify no PII)
cat scripts/templates/dbs_template.yaml

# 3. Commit template and code (not real PDF)
git add scripts/templates/dbs_template.yaml scripts/analyzers/ scripts/generators/
git commit -m "Add DBS PDF format template and generators"
```

**Phase 1: Generate Test PDFs (Can Commit Generated PDFs)**
```bash
# Generate test PDFs (using committed templates)
python scripts/generate_pdf_fixtures.py --source dbs --output tmp/fixtures/

# Generated PDFs can be committed (fictional data)
git add tmp/fixtures/dbs/test_dbs_2501.pdf
git commit -m "Add DBS test PDF fixture"
```

### Git Configuration

**`.gitignore` additions:**
```gitignore
# Real PDFs (sensitive, don't commit)
wealth_pipeline/input/**/*.pdf
wealth_pipeline/input/**/*.PDF
*.real.pdf
*.sensitive.pdf

# Local analysis outputs (if contain sensitive info)
*.analysis.json
*.analysis.yaml
!scripts/templates/*.yaml  # But allow committed templates
```

**What CAN be committed:**
- ✅ Format templates (`scripts/templates/*.yaml`) - Only format parameters
- ✅ Analysis tool code (`scripts/analyzers/`)
- ✅ Generation code (`scripts/generators/`)
- ✅ Generated test PDFs (`tmp/fixtures/*.pdf`) - Fictional data
- ✅ Fake data generator (`scripts/data/fake_data.py`)

**What CANNOT be committed:**
- ❌ Real PDF files (any location)
- ❌ Files containing real transaction data
- ❌ Files containing account numbers, names, etc.

### Format Template Structure

**Example: `dbs_template.yaml`**
```yaml
page:
  size: A4
  margins:
    top: 72
    bottom: 72
    left: 72
    right: 72

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

table:
  transaction_details:
    columns:
      - name: Date
        width: 70
        align: left
      - name: Description
        width: 200
        align: left
      - name: Withdrawal
        width: 60
        align: right
      - name: Deposit
        width: 60
        align: right
      - name: Balance
        width: 70
        align: right
    header_style:
      background: "#CCCCCC"
      text_color: "#000000"
    row_style:
      background: "#FFFFFF"
      border: "1px solid #000000"
```

### Testing Strategy

1. **Format Consistency Test**
   - Extract table structure from generated PDF
   - Compare with template (column widths, alignment)
   - Verify within tolerance

2. **Parser Integration Test**
   - Run adapter on generated PDF
   - Verify transactions extracted correctly
   - Verify balance calculations

3. **Visual Comparison** (Manual, local)
   - Compare generated PDF with real PDF
   - Verify layout similarity
   - Document differences

---

## 📚 References

- EPIC-003: Statement Parsing (uses generated PDFs)
- EPIC-008: Testing Strategy (mentions PDF fixtures)
- Existing: `scripts/generate_pdf_fixtures.py` (needs refactoring)
- Adapters: `wealth_pipeline2/src/adapters/` (DBS, CMB, Mari Bank)

---

## 🚀 Next Steps

1. **Review this EPIC** - Get approval on approach
2. **Phase 0**: Create format analyzer, analyze real PDFs (local)
3. **Phase 1**: Implement generators based on templates
4. **Phase 2**: Validation and testing
5. **Phase 3**: Documentation and CI integration

**Critical Path**: Format analysis (Phase 0) must be completed before generation (Phase 1) can begin.
