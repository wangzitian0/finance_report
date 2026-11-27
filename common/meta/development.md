# Development Environment SSOT

> **SSOT Key**: `development` | Local tooling, CLI tasks, DB lifecycle, and branch isolation.

### Toolchain Contract

Pinned in `toolchain.toml` and enforced by `python -m common.runtime.check_toolchain_contract` (Python `3.12.12`, Node `20.19.0`, `npm 10.8.2`, `uv 0.9.18`, Postgres/MinIO container digests). This check is specific to this repository; infra2-sdk has no equivalent (wangzitian0/infra2-sdk#241). Bootstrap via `bash common/runtime/shell/bootstrap.sh`.

### Local Host Shell Matrix

Run commands in POSIX shells (macOS/Linux or WSL Ubuntu on Windows via `wsl.exe -d Ubuntu --cd ... --exec /bin/bash -lc "..."`), never PowerShell/Git Bash, so PATH resolves `podman`, `uv`, `npm`, `gh`, `op`, and `direnv`.

## Development Commands

- Infra & dev: `python -m common.runtime.dev.cli dev`, `make backend`, `make frontend`
- Verification: `make lint`, `python -m common.runtime.dev.cli build`

Local verification is the focused single-process test of the change (`pytest -n0 --no-cov -o addopts= <file>::<test> -x`). CI runs each suite ([ci-cd.md](../testing/ci-cd.md#path-risk-to-local-gate-matrix)).

<a id="local-test-isolation"></a>
### Local Test Isolation

`apps/backend/tests/_support/db_isolation.py` namespaces databases (`finance_report_test_{namespace}`, `_gwN`) and MinIO buckets (`statements-{namespace}`, hash-truncated within 63 chars) on ephemeral localhost ports so parallel worktrees do not collide. A test session drops its database when it ends; `python -m common.testing.reap_test_dbs --all` drops the idle databases that interrupted runs left.

## Environment Variables

`apps/backend/src/config.py`, `common/runtime/required-env.generated.json`, and `.env.example` are kept in sync by `python -m common.runtime.env_manifests --check`. Related: [environments.md](../runtime/environments.md) · [ci-cd.md](../testing/ci-cd.md) · [deployment.md](../runtime/deployment.md).
