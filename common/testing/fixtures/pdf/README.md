# PDF Fixture Tooling

This directory contains code and templates for synthetic PDF bank and brokerage
statement fixtures. The documentation owner is
[`common/testing/readme.md#pdf-fixtures`](../../readme.md#pdf-fixtures).

Common commands:

```bash
python tools/generate_pdf_fixtures.py --source all
python tools/generate_pdf_fixtures.py --source dbs
python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/

python tools/analyze_pdf_fixture.py \
  --input common/testing/fixtures/pdf/input/real_dbs_statement.pdf \
  --output common/testing/fixtures/pdf/templates/dbs_template.yaml \
  --source dbs
```

Local real PDFs go under `input/` and generated PDFs go under `output/`; both
paths are gitignored. Committed `templates/*.yaml` files must contain only
format metadata.
