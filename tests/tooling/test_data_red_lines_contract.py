"""AC7.12.6 (G2, #877) — derived data-lane red lines pinned in SSOT.

The public deploy front door is ``deploy_v2(service, type, version_ref, iac_ref)``.
The data lane is derived from the selected environment before red-line checks run;
it is not a public deploy coordinate. These four red lines are *decided constraints*;
they live in ``environments.md`` (the six-environment SSOT) so every environment
inherits them. See EPIC-007 AC7.12.6, root #876.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# Each red line carries a stable label so a doc reword cannot silently drop it,
# plus keywords that pin its meaning.
DATA_RED_LINES = {
    "RL-DATA-1": ["pr", "prod data"],  # unreviewed code never runs on prod data
    "RL-DATA-2": ["anonymiz", "prod"],  # anonymize before data leaves prod
    "RL-DATA-3": ["object storage", "synthetic"],  # non-prod holds no real uploads
    "RL-DATA-4": ["backup", "snapshot"],  # a backup is not an anonymized snapshot
}
# All three data sources (Copilot CR: don't let a regression silently drop one).
# Checked inside the "Data sources" subsection so a stray mention elsewhere in the
# SSOT (e.g. the Staging environment) cannot satisfy the assertion.
DATA_SOURCES = ["empty", "staging", "anonymized prod snapshot"]


def _subsection(md: str, header: str) -> str:
    """Text from ``header`` up to the next same-or-higher-level heading, lowercased."""
    out, capturing = [], False
    for line in md.splitlines():
        if line.strip() == header:
            capturing = True
            continue
        if capturing and line.startswith("### "):
            break
        if capturing:
            out.append(line)
    return "\n".join(out).lower()


def test_AC7_12_6_environments_define_data_axis_and_red_lines():
    md = read("docs/ssot/environments.md")
    sources = _subsection(md, "### Data sources")
    assert sources, (
        "environments.md must have a '### Data sources' subsection (AC7.12.6, #877)."
    )
    for src in DATA_SOURCES:
        assert src in sources, (
            f"environments.md '### Data sources' must define '{src}' (AC7.12.6, #877)."
        )
    env = md.lower()
    for label, keywords in DATA_RED_LINES.items():
        assert label.lower() in env, (
            f"environments.md must state data red line {label} (AC7.12.6, #877)."
        )
        for kw in keywords:
            assert kw in env, (
                f"data red line {label} must mention '{kw}' (AC7.12.6, #877)."
            )


def test_AC7_12_6_deploy_v2_data_lane_is_derived_not_public_axis():
    """AC7.12.6: root SSOT must not drift back to the retired public primitive."""
    md = read("docs/ssot/environments.md")
    env = md.lower()

    assert "deploy_v2(service, type, version_ref, iac_ref)" in md
    assert "data_lane" in md
    assert "not a public `deploy_v2` coordinate" in md
    assert "derived" in env
    assert "envconfig.data_default" in env
    assert "Staging" in md and "`staging`" in md
    assert "Preview" in md and "`staging`" in md
    assert "Production" in md and "`prod`" in md

    retired_public_contract = "deploy(env, code, " + "data)"
    assert retired_public_contract not in md, (
        "environments.md must describe data_lane as derived from deploy_v2, not as "
        "a public deploy coordinate."
    )
