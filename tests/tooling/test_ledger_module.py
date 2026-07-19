"""ledger module + project-DAG guards (EPIC-012 AC12.34).

The ledger module is the template vertical slice. After the package-model cutover
(#1420 slice 3a) it converges into ``base/`` (the pure double-entry core), ``extension/``
(the posting service + the journal ``Repository`` adapter), and ``data/`` (the
account-balance projection). These guards keep its shape and the project's layer-DAG
rule honest: nouns/verbs/projection converge by layer, the model layer never depends
on a service (no upward edges / import cycles), and the journal write pipeline lives
in the ledger package (no ``services.accounting`` re-export shim survives).
"""

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_ledger_module_shape", ac_ids=["AC-ledger.34.2"], ci_tier="pr_ci"
)
def test_AC12_34_2_ledger_module_converges_by_role():
    """AC-ledger.34.2: ledger converges by layer — base/ (the Entry/Leg nouns), extension/
    (the post_entry verb + the journal Repository adapter), data/ (the balance
    projection) — and exports Entry/Leg/post_entry/UnbalancedEntryError."""
    assert (SRC / "ledger/base/types/entry.py").exists()
    assert (SRC / "ledger/extension/post.py").exists()
    assert (SRC / "ledger/data/balance.py").exists()
    # the retired role dirs are gone (single home, zero residue).
    assert not (SRC / "ledger/types").exists()
    assert not (SRC / "ledger/ops").exists()
    assert not (SRC / "ledger/store").exists()
    exports = _read("apps/backend/src/ledger/__init__.py")
    for name in ("Entry", "Leg", "post_entry", "UnbalancedEntryError"):
        assert name in exports, f"ledger must export {name}"


@ac_proof(
    proof_id="test_models_have_no_service_deps",
    ac_ids=["AC-ledger.34.3"],
    ci_tier="pr_ci",
)
def test_AC12_34_3_model_layer_never_imports_a_service():
    """AC-ledger.34.3: the model layer has no upward edge into services (DAG rule).

    Previously models/journal.py imported services.confidence_tier inside a
    property — a model→service cycle. That edge is gone; this guard prevents any
    model from importing a service again (top-level or in-method). The scan
    covers the unowned ``models/`` remainder AND the per-package ``orm/`` dirs
    the #1675 moves relocated model modules into.
    """
    model_dirs = [SRC / "models", *sorted(SRC.glob("*/orm"))]
    offenders = []
    for path in sorted(p for d in model_dirs for p in d.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            if any(m.startswith("src.services") for m in mods):
                offenders.append(path.name)
    assert not offenders, (
        f"model layer imports services (upward edge): {sorted(set(offenders))}"
    )


@ac_proof(
    proof_id="test_confidence_tier_relocated",
    ac_ids=["AC-ledger.34.3"],
    ci_tier="pr_ci",
)
def test_AC12_34_3_confidence_tier_lives_in_model_layer():
    """AC-ledger.34.3: ledger owns and publishes the confidence-tier mapping."""
    journal = _read("apps/backend/src/ledger/orm/journal.py")
    assert "def derive_confidence_tier(" in journal
    published = _read("apps/backend/src/ledger/__init__.py")
    assert '"ConfidenceTier"' in published
    assert '"derive_confidence_tier"' in published
    assert not (SRC / "reporting/extension/confidence_tier.py").exists()


@ac_proof(
    proof_id="test_ledger_investment_postings_adoption",
    ac_ids=["AC-ledger.34.4"],
    ci_tier="pr_ci",
)
def test_AC12_34_4_investment_postings_use_ledger_post():
    """AC-ledger.34.4: investment buy/sell/dividend post via Entry + post_entry."""
    src = _read("apps/backend/src/portfolio/extension/accounting.py")
    # One published-root import carrying Entry/Leg/post_entry (the ORM names the
    # #1675 D5 move added ride the same line, so match names, not the exact line).
    ledger_imports = [
        line for line in src.splitlines() if line.startswith("from src.ledger import ")
    ]
    assert ledger_imports, (
        "accounting.py must import from the published src.ledger root"
    )
    for name in ("Entry", "Leg", "post_entry"):
        assert any(name in line for line in ledger_imports), (
            f"accounting.py must import {name} from src.ledger"
        )
    assert "Entry.transfer(" in src  # buy
    assert "Entry.of(" in src  # sell + dividend
    # all hand-rolled investment line dicts are gone, and the legacy post path is retired
    for needle in (
        '"event_type": "investment_buy"',
        '"event_type": "investment_sell"',
        '"event_type": "investment_dividend"',
        "create_journal_entry(",
        "_post_and_load(",
    ):
        assert needle not in src, (
            f"investment_accounting should no longer contain {needle!r}"
        )


@ac_proof(
    proof_id="test_ledger_all_posting_paths_balance_guaranteed",
    ac_ids=["AC-ledger.34.5"],
    ci_tier="pr_ci",
)
def test_AC12_34_5_remaining_posting_paths_guard_balance_with_entry():
    """AC-ledger.34.5: the raw-ORM posting paths gate balance through Entry.

    opening-balance, fx-revaluation, and processing-account transfers each
    construct an Entry before persisting (fx-revaluation previously had no balance
    validation at all; processing-account had none either). The remaining raw site
    `review_queue` validates via `validate_journal_balance`/`_posting_invariants`,
    and `reconciliation_audit` is a deterministic audit fixture. So every computed
    or transfer posting path is balance-guaranteed as a type.

    The processing-account transfer postings were folded INTO the ledger package
    (#1420 slice 3b): they now live in ``ledger/extension/processing.py`` and import
    ``Entry`` package-internally (``from src.ledger.base.types.entry import Entry``),
    not via the published root — the same form ``ledger/extension/post.py`` uses.
    """
    # External callers import the published ledger Entry; in-package edges import
    # the base type directly. Both forms still prove "an Entry guards balance".
    for path, entry_import in (
        (
            "apps/backend/src/ledger/extension/accounting.py",
            "from src.ledger import Entry",
        ),
        (
            "apps/backend/src/ledger/extension/fx_revaluation.py",
            "from src.ledger import Entry",
        ),
        (
            "apps/backend/src/ledger/extension/processing.py",
            "from src.ledger.base.types.entry import Entry",
        ),
    ):
        src = _read(path)
        assert entry_import in src, f"{path} must import ledger Entry ({entry_import})"
        assert "Entry.of(" in src or "Entry.transfer(" in src, (
            f"{path} must construct an Entry to guard balance"
        )


@ac_proof(
    proof_id="test_ledger_owns_posting_pipeline",
    ac_ids=["AC-ledger.34.6"],
    ci_tier="pr_ci",
)
def test_AC12_34_6_ledger_owns_posting_pipeline_no_upward_edge():
    """AC-ledger.34.6: the journal write pipeline lives in the ledger package
    behind the anchored command boundary, and no services.accounting re-export survives.
    """
    assert (SRC / "ledger/extension/repository.py").exists()
    post = _read("apps/backend/src/ledger/extension/post.py")
    anchored = _read("apps/backend/src/ledger/extension/anchored_posting.py")
    assert "from src.ledger.extension.anchored_posting import" in post
    assert (
        "from src.ledger.extension.repository import _create_anchored_journal_entry"
        in anchored
    )
    assert "from src.ledger.extension.repository import" not in post
    assert "from src.ledger.extension.accounting import" not in post, (
        "ledger.extension must not import upward into services.accounting"
    )
    acct = _read("apps/backend/src/ledger/extension/accounting.py")
    # the re-export shim is GONE: accounting no longer re-publishes the pipeline,
    # and the pipeline defs do not live here.
    assert "from src.ledger.store.posting import" not in acct
    assert "async def _create_anchored_journal_entry(" not in acct
    assert "async def post_journal_entry(" not in acct
    assert "async def void_journal_entry(" not in acct
    # Callers now reach the guarded pipeline through the published ledger interface.
    assert "from src.ledger import" in acct
