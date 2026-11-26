# `testing` — Cross-Cutting CI Governance Layer

`common/testing/` owns test selection, shared fixtures, coverage policy, and pre-push checks.

## Governance charter

### Execution matrix

[`matrix.py`](./matrix.py) is the SSOT for path -> stage routing (`common/testing/data/test-execution-matrix.yaml`), staging/preview/audit corpora (`common.testing.test_selection --stage ... --run|--shell`), and sharding (`python -m common.testing.backend_shard` over `apps/backend/ci/backend-test-durations.json`). `WORKFLOW_PYTEST_CONTRACTS` binds JUnit-producing workflow invocations.

### Package declaration protocol

Domain packages verify invariants through focused backend/frontend tests, while `common/meta/flows/user_cases_ssot.json` binds the 47 end-to-end business user cases (`UC-01..UC-47`).

### Test Stratification (L1-L4)

- **L1 (Dependency and wiring contracts)**: OpenAPI parity, env manifests, toolchain contracts, router boundaries, and import-layer rules (`tests/tooling/`).
- **L2 (Honest smoke)**: Environment-branched runtime smoke probes (`common/runtime/shell/smoke_test.sh`, `tests/e2e/test_production_readonly_smoke.py`).
- **L3 (Invariant core)**: Seven non-overlapping financial and security invariant pillars registered in [`invariant_core.py`](./invariant_core.py) and selectable via `pytest -m invariant_core`.
- **L4 (Mocked UI and orchestration flows)**: Pruned to essential `user_cases_ssot.json` evidence, telemetry E2E, and visual smoke specs.

### E2E extension layer

Root specs under `tests/e2e/` are declared per file in `matrix.E2E_ROWS` (`llm_provider`, `market_data`, `deployed_env`, `state_sensitive`, `audited`). Provider-free core journeys form `staging_core_e2e` and `preview_minimum_e2e`; `--run` executes them in `matrix.stage_parallelism()` pytest-xdist workers, and `tests/e2e/xdist_order.py` starts each `parse_journey` test first on its own worker (#3241); live-LLM checks split between `canary` (`staging.post`) and `audit_replay` (`scheduled_audit`), while `core_journey` runs only the disjoint non-LLM `CORE_JOURNEY_ONLY_FILES` checkpoints (`tests/e2e/journey_checkpoint.py`). Diagnostic hooks capture `e2e_rate_limit.py` 429s, E2E failure bundles, `transport_retry.py` reconnects, and `description_fidelity.py`.

### Fast interception

Boundary and purity gates run at lint/tooling speed (`check_app_boundary`, `check_base_purity`, `check_tier_imports`, `gate_cli.py`) before runtime CI shards execute.

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

Generates synthetic statements under `tests/fixtures/pdf/` while keeping real statements local and gitignored (`input/`, `output/`).

### Generate Test PDFs

```bash
python -m tests.fixtures.pdf.generate_pdf_fixtures --source dbs
```

Supported `--source` values: `dbs`, `cmb`, `mari`, `moomoo`, `futu`, `pingan`, `all` (templates in `templates/*.yaml`, synthetic rows in `data/fake_data.py`).

### Commit Policy

Commit `templates/*.yaml`, generators, `fake_data.py`, and wrappers; never commit `input/` or `output/` PDFs or real PII.

### Font Fallback

`tests/fixtures/pdf/generators/font_utils.py` exposes `register_chinese_fonts()` and `get_safe_font()` (Helvetica fallback).
