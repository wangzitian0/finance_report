"""AC7.12.6 (G2, #877) — data red lines pinned in SSOT.

The data axis (which data an environment runs on) is the second input to
``deploy(env, code, data)``. Most of this project's risk lives on the data side
(financial correctness, Alembic migrations). These four red lines are *decided
constraints*; they live in ``environments.md`` (the six-environment SSOT) so every
environment inherits them. See EPIC-007 AC7.12.6, root #876.
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
