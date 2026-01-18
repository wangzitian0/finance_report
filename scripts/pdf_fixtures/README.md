# PDF Fixture Generation Tool

This directory contains a complete tool for generating synthetic PDF bank statements for testing.

## Directory Structure

```
pdf_fixtures/
├── generate_pdf_fixtures.py  # Main script
├── analyzers/                 # PDF format analysis tools
│   ├── pdf_analyzer.py
│   └── analyze_pdf.py         # CLI tool
├── generators/                # PDF generators
│   ├── base_generator.py
│   ├── dbs_generator.py
│   ├── cmb_generator.py
│   └── mari_generator.py
├── templates/                 # Format templates (committed)
│   ├── dbs_template.yaml
│   ├── cmb_template.yaml
│   └── mari_template.yaml
├── data/                      # Fictional data generators
│   └── fake_data.py
├── validators/                # Format validation
│   └── pdf_validator.py
├── input/                     # Real PDFs (gitignored, local only)
│   └── .gitkeep
└── output/                    # Generated test PDFs (gitignored)
    └── .gitkeep
```

## Quick Start

### Generate Test PDFs

```bash
# From repository root
cd scripts/pdf_fixtures

# Generate all sources (DBS, CMB, Mari Bank, Moomoo, Pingan)
python generate_pdf_fixtures.py --source all

# Generate specific source
python generate_pdf_fixtures.py --source dbs
python generate_pdf_fixtures.py --source cmb
python generate_pdf_fixtures.py --source mari
python generate_pdf_fixtures.py --source moomoo
python generate_pdf_fixtures.py --source pingan

# Output will be in: output/{source}/test_{source}_{period}.pdf
```

### Analyze Real PDF (Offline, Local Only)

```bash
# 1. Place real PDF in input/ directory (not committed)
cp ~/real_dbs_statement.pdf input/

# 2. Analyze and extract format template
python analyzers/analyze_pdf.py \
  --input input/real_dbs_statement.pdf \
  --output templates/dbs_template.yaml \
  --source dbs

# 3. Review template (verify no sensitive data)
cat templates/dbs_template.yaml

# 4. Commit updated template (not the real PDF)
git add templates/dbs_template.yaml
git commit -m "Update DBS format template"
```

## Usage

### Generate PDFs

```bash
# From pdf_fixtures directory
python generate_pdf_fixtures.py --source dbs
python generate_pdf_fixtures.py --source cmb
python generate_pdf_fixtures.py --source mari
python generate_pdf_fixtures.py --source all

# Custom output directory
python generate_pdf_fixtures.py --source dbs --output /path/to/output/
```

### Analyze Real PDF

```bash
# Analyze real PDF and create/update template
python analyzers/analyze_pdf.py \
  --input input/real_pdf.pdf \
  --output templates/source_template.yaml \
  --source dbs
```

## Input and Output

- **`input/`**: Place real PDFs here for analysis (gitignored, not committed)
- **`output/`**: Generated test PDFs are saved here (gitignored by default)

Both directories are gitignored to protect sensitive information.

## Format Templates

Format templates (`templates/*.yaml`) define:
- Page layout (size, margins)
- Fonts (family, size)
- Table structure (columns, widths, alignment)
- Text element positions

**Important**: Templates contain **format information only**, no transaction data or sensitive information.

## What Can Be Committed

✅ **Can be committed:**
- Format templates (`templates/*.yaml`)
- All code files (`analyzers/`, `generators/`, `data/`, `validators/`)
- `generate_pdf_fixtures.py`
- This README

❌ **Cannot be committed (gitignored):**
- `input/` directory (real PDFs)
- `output/` directory (generated PDFs, unless explicitly needed)

## Dependencies

- `reportlab` - PDF generation
- `pdfplumber` - PDF analysis (for analyzers)
- `pyyaml` - YAML template support

Install with:
```bash
pip install reportlab pdfplumber pyyaml
```

## Integration with Tests

Generated PDFs can be used in:
- E2E tests
- Adapter unit tests
- Regression tests

Example:
```python
# In test file
from pathlib import Path
pdf_path = Path("scripts/pdf_fixtures/output/dbs/test_dbs_2501.pdf")
# Use PDF for testing...
```

## Workflow

1. **Analyze Real PDF** (local, offline):
   ```bash
   python analyzers/analyze_pdf.py --input input/real.pdf --output templates/template.yaml --source dbs
   ```

2. **Review Template**:
   ```bash
   cat templates/template.yaml
   # Verify no sensitive data
   ```

3. **Commit Template**:
   ```bash
   git add templates/template.yaml
   git commit -m "Update format template"
   ```

4. **Generate Test PDFs**:
   ```bash
   python generate_pdf_fixtures.py --source dbs
   # Output: output/dbs/test_dbs_2501.pdf
   ```

## See Also

- EPIC-009: PDF Fixture Generation (`docs/project/EPIC-009.pdf-fixture-generation.md`)
- Adapters: `wealth_pipeline2/src/adapters/` (DBS, CMB, Mari Bank)
