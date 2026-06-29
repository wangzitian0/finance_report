"""CLI actions + entrypoint."""

from __future__ import annotations


from tools._lib.dev.pr_preview_lifecycle import _dokploy

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

from tools._lib.dev.pr_preview_lifecycle._base import (
    PR_PREVIEW_CONTEXT_ENV,
    PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
    PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
)
from tools._lib.dev.pr_preview_lifecycle._dokploy import (
    DokployConfig,
    DokployDeploymentDidNotStart,
    DokployDeploymentFailed,
    capture_compose_state,
    configure_preview_compose,
    create_compose,
    fail_before_readiness_after_missing_record,
    restore_compose_state,
)
from tools._lib.dev.pr_preview_lifecycle._preview import (
    build_preview_context,
    build_preview_env,
    preview_app_url,
    validate_deploy_inputs,
    write_preview_context,
)
from tools._lib.dev.pr_preview_lifecycle._util import (
    deployment_ids,
    deployment_signatures,
    normalize_dash_prefixed_values,
    parse_positive_int_env,
    redact_diagnostic_value,
)


def deploy_action(args: argparse.Namespace) -> int:
    validate_deploy_inputs(args)
    config = DokployConfig(api_url=args.api_url, api_key=args.api_key)
    context_path = os.environ.get(PR_PREVIEW_CONTEXT_ENV, "")
    compose_id = ""
    # Tracks which mutation the compose was left at and the last-known-good
    # snapshot to roll back to on failure (issue #758). "step" advances as the
    # deploy mutates source -> env -> deploy -> rollout. "good" is None until we
    # have a snapshot worth restoring (only existing composes have one).
    mutation: dict[str, object] = {"step": "preflight", "good": None}

    def record_context(
        phase: str,
        *,
        error: str = "",
        mutation_step: str = "",
        recovery_state: str = "",
    ) -> None:
        write_preview_context(
            context_path,
            build_preview_context(
                args,
                phase=phase,
                compose_id=compose_id,
                error=error,
                mutation_step=mutation_step,
                recovery_state=recovery_state,
            ),
        )

    record_context("preflight")
    try:
        compose_id, existing_compose = _dokploy.get_or_create_compose_with_status(
            config,
            environment_id=args.environment_id,
            compose_name=args.compose_name,
            pr_number=args.pr_number,
            branch=args.branch,
            github_integration_id=args.github_integration_id,
        )
        record_context("compose-resolved")
        existing_compose_data = (
            _dokploy.get_compose_data(config, compose_id=compose_id)
            if existing_compose
            else {}
        )
        if (
            existing_compose
            and str(existing_compose_data.get("composeStatus") or "") == "idle"
            and not deployment_ids(existing_compose_data.get("deployments"))
        ):
            print(
                "Existing preview compose has no deployment records; "
                "recreating before deploy"
            )
            _dokploy.delete_compose(config, compose_id=compose_id)
            compose_id = create_compose(
                config,
                environment_id=args.environment_id,
                compose_name=args.compose_name,
                pr_number=args.pr_number,
                branch=args.branch,
                github_integration_id=args.github_integration_id,
            )
            existing_compose = False
            record_context("compose-recreated")

        preview_env = build_preview_env(
            pr_number=args.pr_number,
            commit_sha=args.commit_sha,
            registry=args.registry,
            image_prefix=args.image_prefix,
            internal_domain=args.internal_domain,
        )

        def configure_current_compose() -> None:
            # Snapshot the last-known-good source/env of an *existing* compose
            # before mutating it, so a later rollout failure can roll back rather
            # than leave a half-updated compose (issue #758). A freshly-created
            # compose has no good state to restore, so leave the snapshot unset
            # and fall back to the marked safe-to-reconcile path.
            if existing_compose and mutation["good"] is None:
                mutation["good"] = capture_compose_state(config, compose_id=compose_id)

            def mark_step(step: str) -> None:
                mutation["step"] = step

            configure_preview_compose(
                config,
                compose_id=compose_id,
                args=args,
                preview_env=preview_env,
                on_step=mark_step,
            )

        def trigger_and_wait(*, force_redeploy: bool) -> None:
            compose_data = _dokploy.get_compose_data(config, compose_id=compose_id)
            previous_deployment_ids = deployment_ids(compose_data.get("deployments"))
            previous_deployment_signatures = deployment_signatures(
                compose_data.get("deployments")
            )
            mutation["step"] = "deploy"
            _dokploy.deploy_compose(
                config, compose_id=compose_id, force_redeploy=force_redeploy
            )
            _dokploy.print_compose_summary(
                config,
                compose_id=compose_id,
                label="after-redeploy-trigger"
                if force_redeploy
                else "after-deploy-trigger",
            )
            record_context(
                "redeploy-triggered" if force_redeploy else "deploy-triggered"
            )
            mutation["step"] = "rollout"
            _dokploy.wait_for_dokploy_deployment_rollout(
                config,
                compose_id=compose_id,
                previous_deployment_ids=previous_deployment_ids,
                previous_deployment_signatures=previous_deployment_signatures,
                new_deployment_timeout_seconds=parse_positive_int_env(
                    PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS_ENV,
                    PR_PREVIEW_NEW_DEPLOYMENT_TIMEOUT_SECONDS,
                ),
            )

        def recreate_compose_before_retry() -> None:
            nonlocal compose_id, existing_compose
            # The compose is being torn down and recreated fresh; there is no
            # prior good state to roll back to anymore.
            mutation["good"] = None
            _dokploy.delete_compose(config, compose_id=compose_id)
            compose_id = create_compose(
                config,
                environment_id=args.environment_id,
                compose_name=args.compose_name,
                pr_number=args.pr_number,
                branch=args.branch,
                github_integration_id=args.github_integration_id,
            )
            existing_compose = False
            record_context("compose-recreated")
            configure_current_compose()

        configure_current_compose()

        try:
            trigger_and_wait(force_redeploy=existing_compose)
        except DokployDeploymentDidNotStart:
            if existing_compose:
                print(
                    "Existing PR preview compose did not complete a new Dokploy "
                    "rollout; recreating compose before retry."
                )
                recreate_compose_before_retry()
                try:
                    trigger_and_wait(force_redeploy=False)
                except DokployDeploymentDidNotStart as retry_error:
                    fail_before_readiness_after_missing_record(
                        compose_id=compose_id,
                        error=retry_error,
                    )
                    record_context("failed", error=str(retry_error))
                    raise
            else:
                print(
                    "Initial Dokploy deploy did not create a deployment record; "
                    "retrying with compose.redeploy"
                )
                try:
                    trigger_and_wait(force_redeploy=True)
                except DokployDeploymentDidNotStart:
                    print(
                        "New PR preview compose still did not create a Dokploy "
                        "deployment record after redeploy; recreating compose "
                        "before final retry."
                    )
                    recreate_compose_before_retry()
                    try:
                        trigger_and_wait(force_redeploy=False)
                    except DokployDeploymentDidNotStart as recreate_error:
                        fail_before_readiness_after_missing_record(
                            compose_id=compose_id,
                            error=recreate_error,
                        )
                        record_context("failed", error=str(recreate_error))
                        raise
        except DokployDeploymentFailed:
            if not existing_compose:
                raise
            print(
                "Existing PR preview compose did not complete a new Dokploy "
                "rollout; recreating compose before retry."
            )
            recreate_compose_before_retry()
            trigger_and_wait(force_redeploy=False)

        record_context("rollout-ready")

        if github_output := os.environ.get("GITHUB_OUTPUT"):
            with open(github_output, "a", encoding="utf-8") as output:
                output.write(f"compose_id={compose_id}\n")
                output.write(
                    f"app_url={preview_app_url(args.pr_number, args.commit_sha, args.internal_domain)}\n"
                )
        else:
            print(f"compose_id={compose_id}")
            print(
                f"app_url={preview_app_url(args.pr_number, args.commit_sha, args.internal_domain)}"
            )
        return 0
    except Exception as exc:
        # Issue #758: never leave a silent half-update. If we mutated an existing
        # compose, roll it back to the captured last-known-good source/env;
        # otherwise (a freshly-created or already-recreated compose) explicitly
        # mark the record safe-to-reconcile so a retry/reconcile knows the
        # compose is not a trustworthy running state. Always record which
        # mutation step the compose was left at.
        mutation_step = str(mutation.get("step") or "preflight")
        recovery_state = "marked-safe-to-reconcile"
        good_state = mutation.get("good")
        if isinstance(good_state, dict) and compose_id:
            try:
                restore_compose_state(config, compose_id=compose_id, state=good_state)
                recovery_state = "rolled-back"
            except Exception as rollback_exc:  # pragma: no cover - defensive
                print(
                    "WARNING: failed to roll preview compose back to "
                    f"last-known-good; left safe-to-reconcile: "
                    f"{type(rollback_exc).__name__}: "
                    f"{redact_diagnostic_value(rollback_exc)}"
                )
        print(
            "PR preview deploy left compose in a recovery state: "
            f"compose_id={compose_id or 'none'} "
            f"mutation_step={mutation_step} recovery_state={recovery_state}"
        )
        record_context(
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            mutation_step=mutation_step,
            recovery_state=recovery_state,
        )
        print(
            "PR preview deploy failed: "
            f"{type(exc).__name__}: {redact_diagnostic_value(exc)}"
        )
        return 1


def main_from_args(args: argparse.Namespace) -> int:
    if args.action == "deploy":
        return deploy_action(args)
    raise ValueError(f"Unsupported action: {args.action}")


def main(argv: list[str] | None = None) -> int:
    # This tool only stands PR previews UP (`deploy`). Preview RECLAIM (the former
    # cleanup/delete/reconcile actions) is owned by infra2 — the app must not touch
    # the Dokploy API. On PR close the app dispatches a vendor-neutral
    # `preview-teardown` signal and infra2's preview-teardown.yml performs the
    # authoritative 1:1 teardown via deploy_v2; infra2's preview-leak-check is the
    # detection fallback.
    argv = normalize_dash_prefixed_values(
        list(argv) if argv is not None else sys.argv[1:]
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=["deploy"], default="deploy")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--compose-name", required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--github-integration-id", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--registry", default="ghcr.io")
    parser.add_argument("--image-prefix", default="")
    parser.add_argument("--internal-domain", default="zitian.party")
    return main_from_args(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
