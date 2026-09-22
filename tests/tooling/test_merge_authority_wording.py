r"""Guard against reintroducing "agents never merge" wording (issue #2069).

The owner granted agents conditional merge authority, scoped entirely by
`docs/contributing/branch-policy.md` §4 (2026-09-21, confirmed 2026-09-22 to
cover every repo the owner owns — see the workspace-root `AGENTS.md`
"合流授权" section). Before this guard, four other places still told every
agent the opposite: `docs/agents/red-lines.md` said "Agent NEVER merges a PR
automatically" / "Merging = User's authority, not Agent's"; `orchestration.md`
said "A mergeable PR (NOT merged code)" and "User merges PR"; `AGENTS.md`
itself said "until the user merges" and "user-only action (merging...)" ten
lines after granting conditional authority; and `branch-policy.md` §4's own
"Merging triggers no deploy" condition could never be satisfied by any PR,
because `.github/workflows/notify-infra2.yml` redeploys a preview slot after
every green `main` CI run.

`red-lines.md` is the file `AGENTS.md` sends every agent to first — as a
red line it wins over a conditional grant read later, so agents defaulted to
handing the merge back (observed in PR #2065's "implementer does not merge;
owner reviews", and the same pattern in infra2 and truealpha).

This test greps the same file scope with the same phrases as issue #2069's
acceptance check:

    git grep -n -i -E "never merge|user merges pr|not merged code|\
user-only action \(merging|triggers no deploy" AGENTS.md docs/agents \
docs/contributing

so the two can never drift apart. Merge authority has exactly one source —
`branch-policy.md` §4 — and every other doc may only point at it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Same phrases, same case-insensitivity, as issue #2069's acceptance grep.
FORBIDDEN_PHRASES = (
    "never merge",
    "user merges pr",
    "not merged code",
    "user-only action (merging",
    "triggers no deploy",
)

# Same file scope as `git grep ... AGENTS.md docs/agents docs/contributing`
# (narrowed from the whole `docs/contributing` tree to the one file issue
# #2069 actually names there, so an unrelated future doc under that directory
# doesn't silently widen this guard's blast radius).
TARGET_FILES: tuple[Path, ...] = (
    (ROOT / "AGENTS.md",)
    + tuple(sorted((ROOT / "docs" / "agents").glob("*.md")))
    + (ROOT / "docs" / "contributing" / "branch-policy.md",)
)


def _violations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase in lowered:
                hits.append(
                    f"{path.relative_to(ROOT)}:{lineno}: hit {phrase!r} -> {line.strip()!r}"
                )
    return hits


def test_target_docs_exist() -> None:
    """Guard the guard: an empty/missing file list would let this pass vacuously."""
    assert len(TARGET_FILES) >= 3, (
        f"expected AGENTS.md + docs/agents/*.md + branch-policy.md, got {TARGET_FILES}"
    )
    for path in TARGET_FILES:
        assert path.is_file(), f"expected target doc to exist: {path}"


def test_no_agents_never_merge_wording() -> None:
    """Merge authority has one source (branch-policy.md §4) — no restatement, no ban.

    Mirrors issue #2069's acceptance grep exactly: a future edit that
    reintroduces "agents never merge" language (or an equivalent banned
    phrase) anywhere in this file scope fails here, instead of silently
    forking the merge-authority rule again.
    """
    violations = [hit for path in TARGET_FILES for hit in _violations(path)]
    assert not violations, (
        "found reintroduced 'agents never merge' wording (issue #2069). "
        "Merge authority lives only in docs/contributing/branch-policy.md §4 — "
        "point at it instead of restating or contradicting it:\n"
        + "\n".join(violations)
    )
