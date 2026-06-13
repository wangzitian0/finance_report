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
    assert "release/**" in ci, (
        "ci.yml `on.push.branches` must include release branches so release commits "
        "publish a `:<sha>` image (AC7.12.4, #879)."
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
