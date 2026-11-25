# PDF Fixture Tooling
This directory contains code and templates for synthetic PDF bank and brokerage statement fixtures. The documentation owner is [`common/testing/readme.md#pdf-fixtures`](../../readme.md#pdf-fixtures). Common commands:
```bash python tools/generate_pdf_fixtures.py --source all  python tools/generate_pdf_fixtures.py --source dbs  python tools/generate_pdf_fixtures.py --source dbs --output /path/to/output/ ```
Local real PDFs go under `input/` and generated PDFs go under `output/`; both paths are gitignored. Committed `templates/*.yaml` files must contain only format metadata.
## PDF Fixture Taxonomy
1. **External real-world benchmark PDFs** (`tests/fixtures/benchmarks/bankstatemently/bsb_001..005.pdf`) — real external layouts used to catch layout, balance-derivation, sign-convention, and multi-currency bugs. 2. **PII-masked statement corpus readings** (`tests/fixtures/readings/`) — 10 PII-redacted LLM outputs replayed through `test_statement_corpus_journeys.py` without raw PII PDFs (`RL-6`).
3. **Generated institution PDFs** (`tests/fixtures/pdf/generated/`) — deterministic multi-institution fixtures pinned in `tests/fixtures/benchmarks/manifest.yaml`.
