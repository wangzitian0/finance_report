# PDF Format Analysis

Full analyzer policy is owned by
[`common/testing/readme.md#pdf-fixtures`](../../../readme.md#pdf-fixtures).

Real PDFs must stay local under `common/testing/fixtures/pdf/input/`; that path
is gitignored because statements may contain sensitive data. Analyzer output
must contain format-only metadata.

```bash
python tools/analyze_pdf_fixture.py \
  --input common/testing/fixtures/pdf/input/real_dbs_statement.pdf \
  --output common/testing/fixtures/pdf/templates/dbs_template.yaml \
  --source dbs
```
