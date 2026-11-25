# Development Environment SSOT

> **SSOT Key**: `development` | Local tooling, Moon tasks, DB lifecycle, and branch isolation.

### Toolchain Contract

Pinned in `toolchain.toml` and enforced by `tools/check_toolchain_contract.py` (Python `3.12.12`, Node `20.19.0`, `npm 10.8.2`, `uv 0.9.18`, Postgres/MinIO container digests). This check is specific to this repository; infra2-sdk has no equivalent (wangzitian0/infra2-sdk#241). Bootstrap via `bash tools/bootstrap.sh` (`common/runtime/shell/`).

### Local Host Shell Matrix

Run commands in POSIX shells (macOS/Linux or WSL Ubuntu on Windows via `wsl.exe -d Ubuntu --cd ... --exec /bin/bash -lc "..."`), never PowerShell/Git Bash, so PATH resolves `podman`, `uv`, `npm`, `gh`, `op`, and `direnv`.

<a id="moon-commands"></a>
## Moon Commands

- Infra & dev: `python tools/cli.py dev`, `moon run :dev -- --backend`, `moon run :dev -- --frontend`
- Verification: `moon run :lint`, `moon run :build`

Local verification is the focused single-process test of the change (`pytest -n0 --no-cov -o addopts= <file>::<test> -x`). CI runs each suite ([ci-cd.md](../testing/ci-cd.md#path-risk-to-local-gate-matrix)).

<a id="local-test-isolation"></a>
### Local Test Isolation

`apps/backend/tests/_support/db_isolation.py` namespaces databases (`finance_report_test_{namespace}`, `_gwN`) and MinIO buckets (`statements-{namespace}`, hash-truncated within 63 chars) on ephemeral localhost ports so parallel worktrees do not collide. A test session drops its database when it ends; `python tools/reap_test_dbs.py --all` drops the idle databases that interrupted runs left.

## Environment Variables

`apps/backend/src/config.py` and `.env.example` are kept in sync by `tools/check_env_keys.py` (`env_keys.py`). Related: [environments.md](../runtime/environments.md) · [ci-cd.md](../testing/ci-cd.md) · [deployment.md](../runtime/deployment.md).
