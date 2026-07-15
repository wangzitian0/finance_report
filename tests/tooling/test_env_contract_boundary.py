"""Anti-regression guard for the App/Infra env/observability contract boundary.

EPIC Infra-014, slice D1.

Principle: infra2 (runtime) owns + issues the env/observability contract; the
App (software) consumes it via ``config.py`` and fast-fails. The App must NOT
re-grow a parallel contract. These string-based assertions fail if the App's
SSOT docs lose their pointer to the infra2 owner, re-introduce a drift pattern,
or if ``config.py`` starts hardcoding a per-env OpenPanel client-id map.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OBSERVABILITY_DOC = ROOT / "common" / "observability" / "observability.md"
ENVIRONMENTS_DOC = ROOT / "common" / "runtime" / "environments.md"
CONFIG_PY = ROOT / "apps" / "backend" / "src" / "config.py"

# Pointers each App doc MUST keep to the infra2-owned contract.
OPS_OBSERVABILITY_POINTER = "https://github.com/wangzitian0/infra2/blob/main/docs/ssot/ops.observability.md"
CORE_ENVIRONMENTS_POINTER = "https://github.com/wangzitian0/infra2/blob/main/docs/ssot/core.environments.md"

# Drift patterns the App docs MUST NOT contain.
#
# The old wrong value is exactly ``deployment.environment=prod``. We must NOT
# flag the legitimate ``deployment.environment=production`` used in App-side
# verification text, so match ``...=prod`` only when it is not the prefix of a
# longer word (i.e. followed by a non-word char or end of string).
WRONG_DEPLOYMENT_ENV_RE = re.compile(r"deployment\.environment=prod(?![A-Za-z0-9_])")
PER_ENV_COLLECTOR_FORM = "platform-signoz-otel-collector${ENV_SUFFIX}"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


def test_observability_doc_points_to_infra2_contract() -> None:
    text = _read(OBSERVABILITY_DOC)
    assert OPS_OBSERVABILITY_POINTER in text, (
        "common/observability/observability.md must point at the infra2-owned contract "
        f"({OPS_OBSERVABILITY_POINTER})"
    )
    assert CORE_ENVIRONMENTS_POINTER in text, (
        "common/observability/observability.md must point at the infra2-owned contract "
        f"({CORE_ENVIRONMENTS_POINTER})"
    )


def test_environments_doc_points_to_infra2_contract() -> None:
    text = _read(ENVIRONMENTS_DOC)
    assert OPS_OBSERVABILITY_POINTER in text, (
        "common/runtime/environments.md must point at the infra2-owned contract "
        f"({OPS_OBSERVABILITY_POINTER})"
    )
    assert CORE_ENVIRONMENTS_POINTER in text, (
        "common/runtime/environments.md must point at the infra2-owned contract "
        f"({CORE_ENVIRONMENTS_POINTER})"
    )


def test_app_docs_do_not_re_grow_contract_drift() -> None:
    for doc in (OBSERVABILITY_DOC, ENVIRONMENTS_DOC):
        text = _read(doc)
        assert WRONG_DEPLOYMENT_ENV_RE.search(text) is None, (
            f"{doc.relative_to(ROOT)} re-introduced the wrong contract value "
            "'deployment.environment=prod'; the App must not restate "
            "deployment.environment values (infra2 owns them)."
        )
        assert PER_ENV_COLLECTOR_FORM not in text, (
            f"{doc.relative_to(ROOT)} re-introduced a per-env collector "
            f"endpoint '{PER_ENV_COLLECTOR_FORM}'; the App must not restate "
            "collector endpoints (infra2 owns the single no-suffix collector)."
        )


def test_config_py_does_not_hardcode_openpanel_client_map() -> None:
    text = _read(CONFIG_PY)
    assert "openpanel_clients" not in text, (
        "apps/backend/src/config.py must not hardcode a per-env "
        "'openpanel_clients' map; per-env OpenPanel client ids are issued by "
        "infra2 (they live in infra2 deploy tooling, not the App config)."
    )
