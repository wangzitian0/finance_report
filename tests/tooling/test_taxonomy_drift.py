"""AC-meta.vocab.1 — the retired-vocabulary (taxonomy-drift) gate.

The package taxonomy migrated: klass ``kernel<platform<core`` -> the five-layer
``PACKAGE_LAYER`` map; ``types/ops/store/api`` roles -> ``base/extension/data``
layers; ``asset_evaluation`` -> ``pricing``. Docs/EPICs/SSOT/tests that present
the retired vocabulary as *current* truth are drift; a mention is legitimate
only when a nearby marker (``formerly`` / ``replaces`` / ``retired`` / ...)
frames it as historical. ``check_taxonomy_drift`` is the executable form of
that rule; these tests pin its behavior and keep the live repo clean.
"""

from __future__ import annotations

from common.meta.extension.check_taxonomy_drift import main, scan_lines


def _findings(text: str, path: str = "docs/example.md"):
    return scan_lines(path, text.splitlines())


class TestRuleEngine:
    def test_AC_meta_vocab_1_unmarked_klass_trio_is_flagged(self):
        """AC-meta.vocab.1: the retired kernel/platform/core klass trio is drift."""
        assert _findings("the three classes core/platform/kernel decide it")
        assert _findings("pick the `klass` (`kernel` < `platform` < `core`)")
        assert _findings('declare klass="kernel" in the contract')

    def test_AC_meta_vocab_1_unmarked_role_folders_are_flagged(self):
        """AC-meta.vocab.1: types/ops/store/api role language is drift."""
        assert _findings("files converge into types/ops/store/api roles")
        assert _findings("## Roles (files converge by role)")

    def test_AC_meta_vocab_1_asset_evaluation_is_flagged(self):
        """AC-meta.vocab.1: the pre-pricing package name is drift."""
        assert _findings("the asset_evaluation package owns valuations")

    def test_AC_meta_vocab_1_backticked_kernel_class_word_is_flagged(self):
        """AC-meta.vocab.1: `kernel` used as a class word is drift."""
        assert _findings("classed as a `kernel` leaf")

    def test_AC_meta_vocab_1_marker_on_same_line_is_allowed(self):
        """AC-meta.vocab.1: a historical marker on the line legitimizes the mention."""
        assert not _findings(
            "internal layering (replaces kernel/platform/core and types/ops/store/api)"
        )
        assert not _findings('(formerly ``klass="kernel"``, now ``infra``)')

    def test_AC_meta_vocab_1_marker_within_two_lines_above_is_allowed(self):
        """AC-meta.vocab.1: the marker window spans a wrapped sentence."""
        text = "layering (replaces kernel/platform/core\nand types/ops/store/api)."
        assert not _findings(text)

    def test_AC_meta_vocab_1_marker_too_far_above_is_not_enough(self):
        """AC-meta.vocab.1: a marker outside the window does not launder drift."""
        text = "formerly things were different\n\n\n\nuse types/ops/store/api roles"
        assert _findings(text)

    def test_AC_meta_vocab_1_plain_kernel_prose_is_not_flagged(self):
        """AC-meta.vocab.1: 'shared domain kernel' (DDD prose) is not the klass word."""
        assert not _findings("the shared domain kernel owns the value language")


def test_AC_meta_vocab_1_repo_is_clean():
    """AC-meta.vocab.1: the tracked docs/SSOT/EPIC/test surface carries no
    unmarked retired vocabulary (the gate exits 0 on the live repo)."""
    assert main([]) == 0
