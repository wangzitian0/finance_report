"""AC7.12.4 (P1a, #879) — the App publishes the artifact for main + release + on demand.

App is the "build" half of the boundary: it publishes the env-independent `:<sha>` image
(G1) that Infra promotes. This contract pins the *publish* side: `ci.yml` pushes `:<sha>`
for `main` and release-branch (`release/**`) commits, and `workflow_dispatch` can publish
an arbitrary sha on demand (the rare "preview an unmerged commit" escape hatch).

Dropping per-PR auto-preview (deploy-preview job) is P1a-2, tracked separately under #879.
See EPIC-007 AC7.12.4, root #876.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# The publish condition must cover all three triggers.
_PUBLISH_TRIGGERS = (
    "refs/heads/main",
    "refs/heads/release/",
    "github.event_name == 'workflow_dispatch'",
)


def test_AC7_12_4_release_branches_trigger_the_publish_workflow():
    ci = read(".github/workflows/ci.yml")
    # Target the actual `branches:` line(s), not a stray mention in a comment, so the
    # contract can't false-pass (Copilot CR).
    branches_lines = [
        ln for ln in ci.splitlines() if ln.strip().startswith("branches:")
    ]
    assert any("release/**" in ln for ln in branches_lines), (
        "ci.yml `on.push.branches` must include release branches so release commits "
        f"publish a `:<sha>` image (AC7.12.4, #879). branches lines: {branches_lines}"
    )


def test_AC7_12_4_image_push_publishes_for_main_release_and_dispatch():
    ci = read(".github/workflows/ci.yml")
    push_lines = [ln for ln in ci.splitlines() if ln.strip().startswith("push: ${{")]
    assert push_lines, (
        "ci.yml must have container-image `push:` conditions (AC7.12.4, #879)."
    )
    for line in push_lines:
        for trigger in _PUBLISH_TRIGGERS:
            assert trigger in line, (
                f"the published-image push condition must cover `{trigger}` so the App "
                f"publishes for main, release branches, and on-demand dispatch "
                f"(AC7.12.4, #879). Offending line: {line.strip()}"
            )

    # The registry login must run under the same triggers, else login is skipped and
    # the push fails only for release/** or workflow_dispatch (Copilot CR).
    login_block = ci.split("- name: Log in to Container registry", 1)[1].split(
        "- name:", 1
    )[0]
    login_if = next(
        (ln for ln in login_block.splitlines() if ln.strip().startswith("if:")), ""
    )
    for trigger in _PUBLISH_TRIGGERS:
        assert trigger in login_if, (
            f"the registry-login `if:` must cover `{trigger}` so login runs whenever the "
            f"image push runs (AC7.12.4, #879). Login if: {login_if.strip()}"
        )


def test_AC7_12_4_persistent_preview_is_on_demand_not_per_pr():
    pr = read(".github/workflows/pr-test.yml")
    # deploy-preview runs only via manual workflow_dispatch — no per-PR auto-deploy (P1a-2).
    deploy_block = pr.split("  deploy-preview:", 1)[1].split("\n  e2e:", 1)[0]
    deploy_if = next(
        (ln for ln in deploy_block.splitlines() if ln.strip().startswith("if:")), ""
    )
    assert "github.event_name == 'workflow_dispatch'" in deploy_if, (
        "the persistent Dokploy preview (deploy-preview) must run only via manual "
        f"workflow_dispatch; per-PR auto-preview is removed (P1a-2, #879). if: {deploy_if.strip()}"
    )
    # The in-runner e2e merge gate stays automatic — it must NOT require workflow_dispatch.
    e2e_block = pr.split("\n  e2e:", 1)[1].split("\n  cleanup:", 1)[0]
    e2e_if = next(
        (ln for ln in e2e_block.splitlines() if ln.strip().startswith("if:")), ""
    )
    assert "workflow_dispatch" not in e2e_if, (
        "the in-runner e2e merge gate must stay automatic, not gated on workflow_dispatch "
        f"(P1a-2, #879). e2e if: {e2e_if.strip()}"
    )
