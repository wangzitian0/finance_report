# PDF Format Analysis

The analyzer tools inspect local real bank PDFs and extract format-only metadata
for synthetic fixture generation.

## Local-Only Input

Place real PDFs under `scripts/pdf_fixtures/input/`. This directory is
gitignored and must stay local because it may contain sensitive statement data.

## Extract a Template

```bash
cd scripts/pdf_fixtures
python analyzers/analyze_pdf.py \
  --input input/real_dbs_statement.pdf \
  --output templates/dbs_template.yaml \
  --source dbs
```

Review the generated YAML before committing it. Committed templates must contain
only layout, font, table, and text-element metadata. Do not commit real PDFs,
account numbers, customer names, transaction payloads, or balances copied from a
real statement.

## Files

- `pdf_analyzer.py`: extracts page, font, table, and text-position metadata.
- `template_extractor.py`: writes sanitized YAML templates from analyzer output.
- `analyze_pdf.py`: CLI wrapper for local analysis and template extraction.
