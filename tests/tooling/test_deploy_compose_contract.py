"""AC7.12.3 (P1b, #878) — the staging/prod deploy path is pull-not-build, data survives redeploy.

Infra consumes the exact artifact digest; it never re-builds. The real staging/prod
deploy compose is the infra2 submodule ``10.app/compose.yaml`` (deployed via Dokploy
``STAGING_COMPOSE_ID`` / ``PRODUCTION_COMPOSE_ID``) — NOT the root ``docker-compose.yml``,
which stays buildable for the App's self-contained run. Investigation (#878) found the
deploy compose already correct (``pull_policy: always``, no ``build:``) and the data
dirs already bind-mounted via ``${DATA_PATH}``; these tests lock that so it can't regress.

See EPIC-007 AC7.12.3, root #876. Data-volume safety relates to RL-DATA / Dokploy
named-volume reset on redeploy.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

APP_COMPOSE = "repo/finance_report/finance_report/10.app/compose.yaml"
# data service compose -> the in-container data dir that must persist across redeploys
DATA_COMPOSES = {
    "repo/finance_report/finance_report/01.postgres/compose.yaml": "/var/lib/postgresql/data",
    "repo/finance_report/finance_report/02.redis/compose.yaml": "/data",
}
APP_SERVICES = ("backend", "frontend")


def load(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_AC7_12_3_deploy_compose_pull_not_build():
    services = load(APP_COMPOSE)["services"]
    for name in APP_SERVICES:
        svc = services[name]
        assert "build" not in svc, (
            f"{name} in {APP_COMPOSE} must have no `build:` section — Infra consumes the "
            f"published image, it never re-builds (AC7.12.3, #878)."
        )
        assert svc.get("pull_policy") == "always", (
            f"{name} in {APP_COMPOSE} must set `pull_policy: always` so the deploy pulls "
            f"the exact digest instead of serving a stale local image (AC7.12.3, #878)."
        )


def test_AC7_12_3_data_dirs_survive_redeploy():
    for path, data_dir in DATA_COMPOSES.items():
        services = load(path)["services"]
        mounts = [
            v
            for svc in services.values()
            for v in (svc.get("volumes") or [])
            if isinstance(v, str) and v.split(":")[0:2][-1] == data_dir
        ]
        assert mounts, (
            f"{path} must mount a data volume at {data_dir} (AC7.12.3, #878)."
        )
        for mount in mounts:
            source = mount.split(":")[0]
            assert "DATA_PATH" in source, (
                f"{path} must bind-mount {data_dir} via ${{DATA_PATH}}, not a named volume "
                f"that Dokploy wipes on redeploy (AC7.12.3, #878). Found source: {source!r}."
            )
