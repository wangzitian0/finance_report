# `testing` — Cross-Cutting CI Governance Layer

`common/testing/` owns test selection, AC proof graph checks, shared fixtures, and PDF fixture generation (`common/testing/contract.py`).

## Governance charter

### Execution matrix

[`matrix.py`](./matrix.py) is the SSOT for path -> stage routing (`common/testing/data/test-execution-matrix.yaml`), staging/preview/audit corpora (`common.testing.test_selection --stage ... --run|--shell`), and sharding (`backend_shard.py` / `tools/backend_shard_files.py` over `apps/backend/ci/backend-test-durations.json`). `WORKFLOW_PYTEST_CONTRACTS` binds JUnit-producing workflow invocations.

### Package declaration protocol

Domain packages declare their own unit/integration roots in `contract.py`; `matrix` aggregates them without central file-list merge conflicts. Vision proof uses `ac_vision_index` over `vision_anchor`.

### E2E extension layer

Root specs under `tests/e2e/` are declared per file in `matrix.E2E_ROWS` (`llm_provider`, `market_data`, `deployed_env`, `state_sensitive`, `audited`). Provider-free core journeys form `staging_core_e2e`; live-LLM checks split between minimal `canary` (`staging_gate`) and `audit_replay` / `core_journey` (`scheduled_audit`, U1–U14 checkpoints via `tests/e2e/journey_checkpoint.py`). Diagnostic hooks capture `e2e_rate_limit.py` 429s, E2E failure bundles, `transport_retry.py` reconnects, and `description_fidelity.py`.

### Fast interception

Contracts run at lint/tooling speed (`check_package_contract`, `gate_cli.py`, `tool_shim_contract.py`) before runtime CI shards execute.

### Responsibility table

| Failure class | Owner |
|---|---|
| Dependency missing / env / config drift | `runtime` |
| Test selection / execution / reporting | `testing` |
| Weak or missing assertion | Owning package AC / behavior tests |
| Flaky test | `testing` (unless runtime is red) |

## <a id="trusted-year-scenario"></a>TrustedYearScenario

`trusted_year.py` provides a small deterministic multi-source scenario and independent `Decimal` oracle (`scenario_id`, `oracle_kind`).

## <a id="pdf-fixtures"></a>PDF Fixtures

> **SSOT Key**: `pdf_fixtures`

Generates synthetic statements under `common/testing/fixtures/pdf/` while keeping real statements local and gitignored (`input/`, `output/`).

### Generate Test PDFs

```bash
python tools/generate_pdf_fixtures.py --source dbs
```

Supported `--source` values: `dbs`, `cmb`, `mari`, `moomoo`, `futu`, `pingan`, `all` (templates in `templates/*.yaml`, synthetic rows in `data/fake_data.py`).

### Analyze Real PDFs

```bash
python tools/analyze_pdf_fixture.py --input common/testing/fixtures/pdf/input/real.pdf --output common/testing/fixtures/pdf/templates/dbs_template.yaml --source dbs
```

### Commit Policy

Commit `templates/*.yaml`, analyzers, generators, `fake_data.py`, and wrappers; never commit `input/` or `output/` PDFs or real PII.

### Font Fallback

`common/testing/fixtures/pdf/generators/font_utils.py` exposes `register_chinese_fonts()` and `get_safe_font()` (Helvetica fallback). Proven by `tests/tooling/test_pdf_fixture_*.py`.
