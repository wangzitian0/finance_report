"""Tests for EPIC-026 phase 3: the cross-tier LLM-import structural gate.

Covers AC26.7.1 — CODE-ONLY/financial-truth modules are statically proven free of
LLM-layer imports (the cross-tier structural MUST rule, ``authority-tiers.md``
rule 2, made deterministic):

- (a) the REAL tree passes — no protected module imports the LLM layer, and every
  curated protected glob resolves to a real file (the curated set has not drifted);
- (b) a SYNTHETIC source that imports ``src.llm`` (or a raw provider SDK) is
  detected as a violation, while a look-alike module name (``src.llmx``) is not —
  exercised via the impl's pure ``forbidden_imports_in_source`` so no real
  violating import is ever added to the codebase.
"""

from __future__ import annotations

from pathlib import Path

from common.ssot import check_tier_imports as gate

ROOT = Path(__file__).resolve().parents[2]


def test_AC26_7_1_real_tree_has_no_llm_imports_in_protected_modules() -> None:
    """AC26.7.1 (a): the real protected set is clean and fully resolved."""
    # The curated globs must all resolve — a glob matching nothing would let the
    # guard silently shrink.
    assert gate.missing_protected_globs(ROOT) == []
    # And the protected set must actually contain files to protect.
    assert gate.resolve_protected_files(ROOT), "protected set resolved to nothing"
    # The structural rule holds today: no protected module imports the LLM layer.
    assert gate.violations(ROOT) == []
    assert gate.main(["--repo-root", str(ROOT)]) == 0


def test_AC26_7_1_synthetic_llm_import_is_detected() -> None:
    """AC26.7.1 (b): a synthetic CODE-ONLY-style module importing the LLM layer fails."""
    # from-import of the project LLM layer
    src_from = "from src.llm.client import LLMClient\n\ndef calc():\n    return 1\n"
    assert gate.forbidden_imports_in_source(src_from) == [("src.llm.client", "src.llm")]

    # plain import of a raw provider SDK
    src_import = "import anthropic\n"
    assert gate.forbidden_imports_in_source(src_import) == [("anthropic", "anthropic")]

    # apps.backend.src.llm spelling is also forbidden
    src_abs = "from apps.backend.src.llm.factory import make\n"
    assert gate.forbidden_imports_in_source(src_abs) == [
        ("apps.backend.src.llm.factory", "apps.backend.src.llm")
    ]

    # parent-package spelling: `from src import llm` pulls in `src.llm`, so it
    # must be caught even though the from-module is the innocuous parent `src`.
    src_parent = "from src import llm\n"
    assert gate.forbidden_imports_in_source(src_parent) == [("src.llm", "src.llm")]
    src_parent_abs = "from apps.backend.src import llm\n"
    assert gate.forbidden_imports_in_source(src_parent_abs) == [
        ("apps.backend.src.llm", "apps.backend.src.llm")
    ]


def test_AC26_7_1_clean_and_lookalike_sources_are_not_flagged() -> None:
    """AC26.7.1 (b): clean / look-alike imports are false-positive-free."""
    clean = (
        "from decimal import Decimal\n"
        "from src.money.money import Money\n"
        "import src.services.reporting_calc as calc\n"
    )
    assert gate.forbidden_imports_in_source(clean) == []

    # Prefix matching is on dotted boundaries: a module that merely starts with
    # the same letters as a forbidden prefix must NOT match.
    lookalike = "import src.llmx\nfrom src.llm_helpers import noop\nimport openairy\n"
    assert gate.forbidden_imports_in_source(lookalike) == []


def test_AC26_7_1_gate_fails_on_synthetic_violating_tree(tmp_path: Path) -> None:
    """AC26.7.1 (b): main() exits 1 when a protected-style module imports src.llm.

    Build a temp repo whose tree mirrors one protected glob and plant a violating
    import there, then point the gate at it — the real codebase is untouched.
    """
    money_dir = tmp_path / "apps" / "backend" / "src" / "money"
    money_dir.mkdir(parents=True)
    (money_dir / "money.py").write_text(
        "from src.llm.client import LLMClient\n", encoding="utf-8"
    )
    # Satisfy the other protected globs so the run fails on the import violation,
    # not on missing-glob drift. One placeholder file per remaining glob.
    for glob in gate.PROTECTED_MODULE_GLOBS:
        # Strip the trailing filename/pattern to a concrete placeholder path.
        rel = glob.replace("/**/*.py", "/__init__.py")
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("from decimal import Decimal\n", encoding="utf-8")

    assert gate.missing_protected_globs(tmp_path) == []
    found = gate.violations(tmp_path)
    assert ("apps/backend/src/money/money.py", "src.llm.client", "src.llm") in found
    assert gate.main(["--repo-root", str(tmp_path)]) == 1


def test_AC26_7_1_gate_fails_when_protected_glob_resolves_to_nothing(
    tmp_path: Path,
) -> None:
    """AC26.7.1: the curated set cannot silently shrink — an empty tree fails.

    Pointing the gate at a repo with none of the protected files present must be
    reported as curation drift (every glob matches nothing), so a refactor that
    moves/renames a protected module out from under the guard is caught.
    """
    missing = gate.missing_protected_globs(tmp_path)
    assert set(missing) == set(gate.PROTECTED_MODULE_GLOBS)
    assert gate.main(["--repo-root", str(tmp_path)]) == 1
