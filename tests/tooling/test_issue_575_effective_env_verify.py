"""Issue #575 / AC7.14: fixed-env deploys verify effective remote app config.

The legacy shell deploy path has been retired. The contract now lives in infra2's
Python fixed-compose primitive, which deploy_v2 calls for staging and production.
These tests pin the cross-repo contract from the app repo: each deploy writes a
fresh IAC_CONFIG_HASH, waits for a new Dokploy rollout record, and then reads the
effective Dokploy env back before the public health wait.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC7_14_1_verify_runs_after_rollout_and_before_health() -> None:
    """AC7.14.1 AC7.14.4: effective-config verification gates fixed-env deploy success."""
    primitive = read("repo/tools/deploy_primitive.py")
    staging = read(".github/workflows/staging-deploy.yml")
    production = read(".github/workflows/production-release.yml")
    primitive_tests = read("repo/libs/tests/test_deploy_primitive.py")

    assert "def verify_effective_config_hash(" in primitive
    assert "client.get_compose_env(compose_id)" in primitive
    assert '"IAC_CONFIG_HASH"' in primitive
    assert "verify_config: bool = False" in primitive
    assert "verify_effective_config_hash(" in primitive
    assert primitive.index("client.deploy_compose(cfg.compose_id)") < primitive.index(
        "verify_effective_config_hash(\n            client"
    )

    assert "python -m tools.deploy_v2" in staging
    assert "- name: Confirm staging backend health" in staging
    assert staging.index("python -m tools.deploy_v2") < staging.index(
        "- name: Confirm staging backend health"
    )
    assert "python -m tools.deploy_v2" in production
    assert "- name: Confirm production backend health" in production
    assert production.index("python -m tools.deploy_v2") < production.index(
        "- name: Confirm production backend health"
    )

    assert "test_verify_effective_config_hash_returns_on_match" in primitive_tests
    assert "test_verify_effective_config_hash_raises_if_never_advances" in primitive_tests
    assert "test_deploy_verify_config_confirms_pushed_hash_rolled_out" in primitive_tests


def test_AC7_14_2_stale_effective_config_fails_fast_without_secret_echo() -> None:
    """AC7.14.2: stale effective config raises a named failure, not a late health 404."""
    primitive = read("repo/tools/deploy_primitive.py")
    dokploy_client = read("repo/libs/dokploy.py")
    primitive_tests = read("repo/libs/tests/test_deploy_primitive.py")

    verify_block = primitive.split("def verify_effective_config_hash(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "post-deploy config verify failed" in verify_block
    assert "effective IAC_CONFIG_HASH" in verify_block
    assert "expected_hash" in verify_block
    assert "last" in verify_block
    assert "raise RuntimeError" in verify_block
    assert "VAULT_APP_TOKEN" not in verify_block
    assert "DATABASE_URL" not in verify_block

    assert "get_compose_env(self, compose_id: str) -> str" in dokploy_client
    assert "return compose.get(\"env\") or \"\"" in dokploy_client
    assert "test_verify_effective_config_hash_raises_if_never_advances" in primitive_tests


def test_AC7_14_3_no_force_recreate_escape_hatch_remains() -> None:
    """AC7.14.3: stale effective config is fail-closed; reruns use deploy_v2."""
    primitive = read("repo/tools/deploy_primitive.py")
    production = read(".github/workflows/production-release.yml")
    deployment_doc = read("docs/ssot/deployment.md")

    assert "DOKPLOY_ALLOW_FORCE_RECREATE" not in primitive
    assert "force_recreate_stateless_app" not in primitive
    assert "compose.redeploy" not in primitive
    assert "compose.redeploy" not in production
    assert "--no-verify-config" not in production
    assert "manual rerun" in deployment_doc.lower()
    assert "deploy_v2" in deployment_doc


def test_AC7_14_6_rollout_baseline_is_snapshotted_before_mutation() -> None:
    """AC7.14.6: rollout wait compares against the pre-mutation deployment ids."""
    primitive = read("repo/tools/deploy_primitive.py")
    primitive_tests = read("repo/libs/tests/test_deploy_primitive.py")

    baseline = "before_ids = ("
    update = "client.update_compose_env(cfg.compose_id, env_vars=env_vars)"
    deploy = "client.deploy_compose(cfg.compose_id)"
    wait = "wait_for_rollout(client, cfg.compose_id, before_ids, timeout=timeout)"

    assert baseline in primitive
    assert update in primitive
    assert deploy in primitive
    assert wait in primitive
    assert primitive.index(baseline) < primitive.index(update)
    assert primitive.index(update) < primitive.index(deploy)
    assert primitive.index(deploy) < primitive.index(wait)

    assert "test_wait_for_rollout_ignores_pre_existing_records" in primitive_tests
    assert "test_wait_for_rollout_returns_when_a_new_record_reaches_done" in primitive_tests
    assert "test_wait_for_rollout_times_out_if_no_new_record_finishes" in primitive_tests


def test_AC7_14_5_deployment_doc_describes_effective_config_failure_and_recovery() -> None:
    """AC7.14.5: deployment SSOT documents stale effective-config failure + recovery."""
    doc = read("docs/ssot/deployment.md")
    lowered = doc.lower()

    assert "stale" in lowered
    assert "effective" in lowered and "verif" in lowered
    assert "iac_config_hash" in lowered
    assert "deploy_v2" in lowered
    assert "manual rerun" in lowered
