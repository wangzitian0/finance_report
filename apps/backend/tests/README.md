# Backend Tests

Backend tests are organized by SSOT domain and verify package invariants and end-to-end user cases (`common/meta/flows/user_cases_ssot.json`).

## Test Tiers

1. **Pure unit/integration tests**: Deterministic fixtures, zero network (`-m "not slow and not e2e"`).
2. **Recorded replay tests**: `@pytest.mark.vcr` with the fixture `vcr_llm` replays one recording (`tests/**/cassettes/`) in CI with `--record-mode=none`; record again with `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>`; never hand-authored ([`common/llm/readme.md#recordings`](../../../common/llm/readme.md#recordings)).
3. **Staging live-token E2E & 3-statement oracle**: Live `LLM_API_KEY` execution via `runtime-hooks.manifest.json` (`staging_gate` / `scheduled_audit`).

## Commands

Run the focused test of the change before a PR. CI runs the full and parallel suites.

```bash
uv run pytest -n0 --no-cov -o addopts= <file>::<test> -x
```

## SSOT Links

| Need | Source |
|---|---|
| TDD & verification workflow | [tdd.md](../../../common/testing/tdd.md) |
| Test execution stages | [test-execution-matrix.yaml](../../../common/testing/data/test-execution-matrix.yaml) |
| Coverage semantics | [coverage.md](../../../common/testing/coverage.md) |
| Business user cases SSOT | [user_cases_ssot.json](../../../common/meta/flows/user_cases_ssot.json) |
| Traceability exceptions | [traceability-exceptions.md](../../../docs/project/traceability-exceptions.md) |
