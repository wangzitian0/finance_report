# Development Environment SSOT

> **SSOT Key**: `development` | Local tooling, Moon tasks, DB lifecycle, and branch isolation.

### Toolchain Contract

Pinned in `toolchain.toml` and enforced by `tools/check_toolchain_contract.py` (Python `3.12.12`, Node `20.19.0`, `npm 10.8.2`, `uv 0.9.18`, Postgres/MinIO container digests). Bootstrap via `bash tools/bootstrap.sh` (`common/runtime/shell/`).

### Local Host Shell Matrix

Run commands in POSIX shells (macOS/Linux or WSL Ubuntu on Windows via `wsl.exe -d Ubuntu --cd ... --exec /bin/bash -lc "..."`), never PowerShell/Git Bash, so PATH resolves `podman`, `uv`, `npm`, `gh`, `op`, and `direnv`.

<a id="moon-commands"></a>
## Moon Commands

- Infra & dev: `bash tools/infra.sh up|down|logs`, `moon run :dev -- --backend`, `moon run :dev -- --frontend`
- Verification: `moon run :lint`, `moon run :test -- --smart`, `moon run :test -- --fast`, `moon run :test`, `moon run :build`

Default local verification starts with affected fast tests (`moon run :test -- --smart`, focused Vitest, or focused tooling checks). Risk-triggered local escalation applies to accounting, schema migrations (`uv run alembic upgrade head && uv run alembic check`), API contracts, shared `common/tooling`, and deploy configs ([ci-cd.md](../testing/ci-cd.md#path-risk-to-local-gate-matrix)).

<a id="local-test-isolation"></a>
### Local Test Isolation

`tools/test_lifecycle.py` and `common/testing/test_isolation.py` namespace databases (`finance_report_test_{namespace}`, `_gwN`) and MinIO buckets (`statements-{namespace}`, hash-truncated within 63 chars) on ephemeral localhost ports so parallel worktrees do not collide. Clean up via `tools/cleanup_orphaned_dbs.py` or `./tools/cleanup_dev_resources.sh`.

## Environment Variables

`apps/backend/src/config.py` and `.env.example` are kept in sync by `tools/check_env_keys.py` (`env_keys.py`). Related: [environments.md](../runtime/environments.md) · [ci-cd.md](../testing/ci-cd.md) · [deployment.md](../runtime/deployment.md).
