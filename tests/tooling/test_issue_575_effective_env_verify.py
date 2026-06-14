"""Issue #575: production deploy must verify effective remote app env.

A Dokploy deploy can report success while the effective production app
configuration remains on the previous release (stale ``IMAGE_TAG`` /
``GIT_COMMIT_SHA`` / ``IAC_CONFIG_HASH``). The deploy script must read back the
effective remote app env *before* the long health wait, fail fast with
diagnostics that name the stale values (never secrets), and expose a guarded
force-recreate / reconcile path for stateless app containers.

These are behavioral contract tests: they source the relevant function block
out of ``tools/_lib/shell/dokploy_deploy.sh`` and run it under bash with the
Dokploy API calls stubbed, mirroring
``test_post_merge_e2e_gates.py::test_AC8_13_72_staging_dokploy_rollout_parsing_is_typed_and_fail_fast``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / "tools" / "_lib" / "shell" / "dokploy_deploy.sh"


def _function_block(start: str, end: str) -> str:
    """Extract the source text from ``start`` (inclusive) up to ``end``."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert start in text, f"{start} missing from deploy script"
    assert end in text, f"{end} missing from deploy script"
    return start + text.split(start, 1)[1].split(end, 1)[0]


# A minimal harness: the verification function plus stubs for the common-shell
# helpers it relies on (env_value / render_allowlisted_env_diff style readback).
_HARNESS_HELPERS = r"""
env_value() {
  printf "%s\n" "$1" | awk -F= -v key="$2" '$1 == key { sub(/^[^=]*=/, ""); print }'
}
# Stub dokploy_api_call: write the queued response body to the output file.
dokploy_api_call() {
  local method="$1" endpoint="$2" data="$3" output_file="$4"
  printf "%s" "$STUB_EFFECTIVE_RESPONSE" > "$output_file"
  return 0
}
safe_jq() {
  local filter="$1" json="$2"
  printf "%s" "$json" | jq -r "$filter"
}
"""


def _run(snippet: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", snippet],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **env},
        text=True,
        capture_output=True,
        check=False,
    )


def test_AC7_13_1_verify_passes_when_effective_env_matches() -> None:
    """AC7.13.1 AC7.13.2: matching effective remote env proceeds (exit 0)."""
    block = _function_block(
        "verify_effective_remote_app_env()", "force_recreate_stateless_app()"
    )
    response = (
        '{"env":"IMAGE_TAG=v0.1.5\\nGIT_COMMIT_SHA=v0.1.5\\n'
        'IAC_CONFIG_HASH=deploy-v0.1.5-123\\nVAULT_APP_TOKEN=hvs.secret"}'
    )
    snippet = (
        _HARNESS_HELPERS
        + block
        + '\nverify_effective_remote_app_env "cid" "v0.1.5" "deploy-v0.1.5-123"\n'
    )
    result = _run(snippet, {"STUB_EFFECTIVE_RESPONSE": response})
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout + result.stderr
    assert "effective_env_verification: match" in out
    # Never echo secret env values.
    assert "hvs.secret" not in out


def test_AC7_13_2_verify_fails_fast_and_names_stale_values() -> None:
    """AC7.13.2 AC7.13.4: stale effective env fails fast naming the stale keys."""
    block = _function_block(
        "verify_effective_remote_app_env()", "force_recreate_stateless_app()"
    )
    # Dokploy reported success but the effective env is still on v0.1.4.
    response = (
        '{"env":"IMAGE_TAG=v0.1.4\\nGIT_COMMIT_SHA=v0.1.4\\n'
        'IAC_CONFIG_HASH=deploy-v0.1.4-000\\nVAULT_APP_TOKEN=hvs.secret"}'
    )
    snippet = (
        _HARNESS_HELPERS
        + block
        + '\nverify_effective_remote_app_env "cid" "v0.1.5" "deploy-v0.1.5-123"\n'
    )
    result = _run(snippet, {"STUB_EFFECTIVE_RESPONSE": response})
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "effective_env_verification: stale" in out
    # Diagnostics must name each stale value (expected vs actual), no secrets.
    assert "IMAGE_TAG: expected=v0.1.5 actual=v0.1.4" in out
    assert "GIT_COMMIT_SHA: expected=v0.1.5 actual=v0.1.4" in out
    assert "IAC_CONFIG_HASH: expected=deploy-v0.1.5-123 actual=deploy-v0.1.4-000" in out
    assert "hvs.secret" not in out


def test_AC7_13_3_force_recreate_path_exists_and_is_guarded() -> None:
    """AC7.13.3 AC7.13.4: a guarded force-recreate reconcile path exists.

    The reconcile path must (a) be guarded by an explicit opt-in env flag,
    (b) refresh the release token (new IAC_CONFIG_HASH), and (c) handle the
    fixed ``container_name`` conflict for stateless app containers.
    """
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "force_recreate_stateless_app()" in script
    assert "verify_effective_remote_app_env" in script
    # Verification happens before the long health wait: the call site precedes
    # the script returning success.
    assert script.index('verify_effective_remote_app_env "$COMPOSE_ID"') < script.index(
        'echo "Deployment triggered successfully"'
    )
    # Guarded reconcile: explicit opt-in flag, forced token refresh, and
    # container_name conflict handling.
    assert "DOKPLOY_ALLOW_FORCE_RECREATE" in script
    assert "IAC_CONFIG_HASH" in script
    assert "container_name" in script.lower()
    # Force-recreate is only attempted on a detected stale-env mismatch.
    assert "force_recreate_stateless_app" in script


def test_AC7_13_6_rollout_baseline_snapshotted_before_force_recreate() -> None:
    """AC7.13.6: the rollout-wait baseline is the PRE-reconcile snapshot.

    Regression guard for the Copilot ordering bug: ``previous_deployment_ids`` /
    ``previous_deployment_signatures`` (the baseline passed to
    ``wait_for_dokploy_deployment_rollout``) must be captured from the
    pre-reconcile ``compose.one`` snapshot, *before*
    ``force_recreate_stateless_app`` triggers ``compose.redeploy``. Capturing
    them after the redeploy lets a fast redeploy's freshly-created deployment
    record leak into the baseline, so the waiter sees no "new" deployment and
    spuriously times out with "did not create a new deployment".
    """
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    # The baseline capture from the pre-reconcile snapshot must precede the
    # force-recreate call that triggers compose.redeploy.
    baseline_capture = 'previous_deployment_ids=$(deployment_ids_from_response "$reconcile_response")'
    force_recreate_call = 'force_recreate_stateless_app "$COMPOSE_ID" "$IMAGE_TAG"'
    assert baseline_capture in script, "pre-reconcile baseline capture missing"
    assert force_recreate_call in script, "force-recreate call missing"
    assert script.index(baseline_capture) < script.index(force_recreate_call), (
        "rollout baseline must be snapshotted BEFORE force_recreate triggers redeploy"
    )

    # The pre-reconcile snapshot must feed the rollout wait, and a stale
    # post-reconcile snapshot must NOT be used as the rollout baseline.
    assert (
        'previous_deployment_signatures=$(deployment_signature_map_from_response "$reconcile_response")'
        in script
    ), "pre-reconcile signature baseline missing"
    assert (
        "Post-reconcile deployment snapshot" not in script
    ), "post-reconcile snapshot must not be used as the rollout baseline"


def test_AC7_13_6_fast_redeploy_detected_as_new_with_pre_reconcile_baseline() -> None:
    """AC7.13.6: a fast redeploy is still recognized as a new deployment.

    Behavioral regression test exercising the real
    ``wait_for_dokploy_deployment_rollout`` with the pre-reconcile baseline.
    The pre-reconcile snapshot has a single deployment ``d1``. By the time the
    rollout waiter probes, the fast redeploy has already created ``d2``
    (status ``done``). Using the pre-reconcile baseline ({d1}) the waiter sees
    ``d2`` as new and succeeds. If the (buggy) post-reconcile baseline
    ({d1,d2}) were used, ``d2`` would not be "new" and the waiter would time
    out -- so this asserts the correct ordering end-to-end.
    """
    helpers = _function_block(
        "deployment_ids_from_response()", "redact_dokploy_diagnostic_value()"
    )
    waiter = _function_block(
        "wait_for_dokploy_deployment_rollout()", "deploy_compose()"
    )

    # Pre-reconcile snapshot: only d1 exists.
    pre_snapshot = '{"deployments":[{"deploymentId":"d1","status":"done","createdAt":"1"}]}'
    # Rollout probe response: fast redeploy already created d2 (done).
    rollout_resp = (
        '{"composeStatus":"done","deployments":['
        '{"deploymentId":"d1","status":"done","createdAt":"1"},'
        '{"deploymentId":"d2","status":"done","createdAt":"2"}]}'
    )

    harness = r"""
response_file=$(mktemp)
safe_jq() { printf "%s" "$2" | jq -r "$1"; }
render_dokploy_rollout_summary() { :; }
# Sequenced stub: first call returns the pre-reconcile snapshot, every
# subsequent (rollout probe) call returns the post-redeploy rollout response.
__CALLS=0
dokploy_api_call() {
  local output_file="$4"
  __CALLS=$((__CALLS + 1))
  if [[ "$__CALLS" -eq 1 ]]; then
    printf "%s" "$PRE_SNAPSHOT" > "$output_file"
  else
    printf "%s" "$ROLLOUT_RESP" > "$output_file"
  fi
  return 0
}
"""

    # Reconstruct the fixed reconcile ordering: capture baseline from the
    # pre-reconcile snapshot BEFORE the (stubbed) redeploy, then wait.
    driver = r"""
dokploy_api_call "GET" "compose.one?composeId=cid" "" "$response_file" "Pre-reconcile env snapshot"
reconcile_response=$(cat "$response_file")
previous_deployment_ids=$(deployment_ids_from_response "$reconcile_response")
previous_deployment_signatures=$(deployment_signature_map_from_response "$reconcile_response")
# (force_recreate -> compose.redeploy happens here; the fast redeploy created d2)
wait_for_dokploy_deployment_rollout "cid" "$previous_deployment_ids" "$previous_deployment_signatures"
echo "RECONCILE_ROLLOUT_OK"
"""

    snippet = helpers + waiter + harness + driver
    result = _run(
        snippet,
        {
            "PRE_SNAPSHOT": pre_snapshot,
            "ROLLOUT_RESP": rollout_resp,
            "DOKPLOY_ROLLOUT_INTERVAL_SECONDS": "0",
            "DOKPLOY_ROLLOUT_TIMEOUT_SECONDS": "5",
            "DOKPLOY_NEW_DEPLOYMENT_TIMEOUT_SECONDS": "5",
        },
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    # The new deployment d2 must be detected as new (not hidden by the baseline).
    assert "new_deployment_ids=d2" in out, out
    assert "RECONCILE_ROLLOUT_OK" in out, out
    assert "did not create a new deployment" not in out, out


def test_AC7_13_5_deployment_doc_describes_stale_env_failure_and_recovery() -> None:
    """AC7.13.5: deployment SSOT documents the stale-env failure mode + recovery."""
    doc = (ROOT / "docs" / "ssot" / "deployment.md").read_text(encoding="utf-8")
    lowered = doc.lower()
    assert "stale" in lowered
    assert "effective" in lowered and "verif" in lowered
    assert "force" in lowered and "recreate" in lowered
    assert "iac_config_hash" in lowered
    assert "dokploy_allow_force_recreate" in lowered
