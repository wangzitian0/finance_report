# PDF Fixture Tooling

This directory contains code and templates for synthetic PDF bank and brokerage
statement fixtures. The documentation owner is
[`docs/ssot/pdf-fixtures.md`](../../../docs/ssot/pdf-fixtures.md).

Common commands:

```bash
python tools/generate_pdf_fixtures.py --source all
python tools/generate_pdf_fixtures.py --source dbs
python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/

python tools/analyze_pdf_fixture.py \
  --input tools/_lib/pdf_fixtures/input/real_dbs_statement.pdf \
  --output tools/_lib/pdf_fixtures/templates/dbs_template.yaml \
  --source dbs
```

Local real PDFs go under `input/` and generated PDFs go under `output/`; both
paths are gitignored. Committed `templates/*.yaml` files must contain only
format metadata.
