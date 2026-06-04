# PDF Format Analysis

Full analyzer policy is owned by
[`docs/ssot/pdf-fixtures.md`](../../../../docs/ssot/pdf-fixtures.md#analyze-real-pdfs).

Real PDFs must stay local under `tools/_lib/pdf_fixtures/input/`; that path is
gitignored because statements may contain sensitive data. Analyzer output must
contain format-only metadata.

```bash
python tools/analyze_pdf_fixture.py \
  --input tools/_lib/pdf_fixtures/input/real_dbs_statement.pdf \
  --output tools/_lib/pdf_fixtures/templates/dbs_template.yaml \
  --source dbs
```
