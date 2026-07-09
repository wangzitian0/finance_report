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

DEPLOY_DRIFT_SCAN_ROOTS = [
    "docs",
    ".opencode/skills/domain",
    "repo/docs",
    "repo/tools",
    "repo/libs/tests",
    "repo/README.md",
    "repo/finance_report",
    "repo/platform",
]
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".txt", ".toml"}


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


def _scan_text_files():
    for rel in DEPLOY_DRIFT_SCAN_ROOTS:
        path = ROOT / rel
        assert path.exists(), f"deploy drift scan root is missing: {rel}"
        if path.is_file():
            candidates = [path]
        else:
            candidates = [p for p in path.rglob("*") if p.is_file()]
        text_candidates = [p for p in candidates if p.suffix in TEXT_SUFFIXES]
        assert text_candidates, f"deploy drift scan root has no text files: {rel}"
        for candidate in text_candidates:
            yield candidate.relative_to(ROOT), candidate.read_text(encoding="utf-8")


def test_AC7_12_6_environments_define_data_axis_and_red_lines():
    """AC-meta.infra-boundary.6: AC7.12.6: environments.md defines the data-lane sources/defaults and the four data red lines."""
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
    """AC-meta.infra-boundary.7: AC7.12.6: root SSOT must not drift back to the retired public primitive."""
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


def test_deploy_v2_drift_surfaces_do_not_republish_retired_data_axis():
    """Deploy docs/tests/code must not drift back to the retired public data axis."""
    retired_public_contract = "deploy(env, code, " + "data)"
    banned_snippets = {
        retired_public_contract: "retired public deploy tuple",
        'parser.add_argument(\n        "--data"': "primitive data override CLI",
        "invoke fr-app.setup": "old prefixed app setup deploy command",
        "invoke fr-postgres.setup": "old prefixed postgres setup deploy command",
        "invoke fr-redis.setup": "old prefixed redis setup deploy command",
        "invoke finance_report.app.setup": "old namespaced app setup deploy command",
        "invoke finance_report.postgres.setup": "old namespaced postgres setup deploy command",
        "invoke finance_report.redis.setup": "old namespaced redis setup deploy command",
        "invoke postgres.setup": "old platform postgres setup deploy command",
        "invoke redis.setup": "old platform redis setup deploy command",
        "invoke clickhouse.setup": "old platform clickhouse setup deploy command",
        "invoke signoz.setup": "old platform signoz setup deploy command",
        "invoke alerting.setup": "old platform alerting setup deploy command",
        "invoke openpanel.setup": "old platform openpanel setup deploy command",
        "invoke authentik.setup": "old platform authentik setup deploy command",
        "invoke minio.setup": "old platform minio setup deploy command",
        "invoke portal.setup": "old platform portal setup deploy command",
        "invoke prefect.setup": "old platform prefect setup deploy command",
        "invoke activepieces.setup": "old platform activepieces setup deploy command",
        "invoke <service>.setup": "old generic service setup deploy command",
        "v2 public input": "stale data-axis public-input wording",
        "public input": "stale data-axis public-input wording",
        "data-axis side effects": "future data-axis wording",
        "data axis lands": "future data-axis wording",
        "platform services join when the deployer path is unified": "stale platform cutover wording",
        "cutover 未做": "stale platform cutover wording",
        "尚未接管": "stale platform cutover wording",
    }

    offenders = []
    for rel, text in _scan_text_files():
        lowered = text.lower()
        for snippet, reason in banned_snippets.items():
            haystack = lowered if snippet.isascii() else text
            needle = snippet.lower() if snippet.isascii() else snippet
            if needle in haystack:
                offenders.append(f"{rel}: {reason}: {snippet!r}")

    assert not offenders, "deploy_v2 drift found:\n" + "\n".join(offenders)
