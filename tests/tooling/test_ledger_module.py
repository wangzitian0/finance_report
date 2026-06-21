"""ledger module + project-DAG guards (EPIC-012 AC12.34).

The ledger module is the template vertical slice. These guards keep its shape and
the project's layer-DAG rule honest: nouns/verbs converge by role, and the model
layer never depends on a service (no upward edges / import cycles).
"""

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(proof_id="test_ledger_module_shape", ac_ids=["AC12.34.2"], ci_tier="pr_ci")
def test_AC12_34_2_ledger_module_converges_by_role():
    """AC12.34.2: ledger exposes types (nouns) + ops (verbs) as a vertical slice."""
    assert (SRC / "ledger/types/entry.py").exists()
    assert (SRC / "ledger/ops/post.py").exists()
    exports = _read("apps/backend/src/ledger/__init__.py")
    for name in ("Entry", "Leg", "post_entry", "UnbalancedEntryError"):
        assert name in exports, f"ledger must export {name}"


@ac_proof(
    proof_id="test_models_have_no_service_deps", ac_ids=["AC12.34.3"], ci_tier="pr_ci"
)
def test_AC12_34_3_model_layer_never_imports_a_service():
    """AC12.34.3: the model layer has no upward edge into services (DAG rule).

    Previously models/journal.py imported services.confidence_tier inside a
    property — a model→service cycle. That edge is gone; this guard prevents any
    model from importing a service again (top-level or in-method).
    """
    offenders = []
    for path in sorted((SRC / "models").glob("*.py")):
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
    proof_id="test_confidence_tier_relocated", ac_ids=["AC12.34.3"], ci_tier="pr_ci"
)
def test_AC12_34_3_confidence_tier_lives_in_model_layer():
    """AC12.34.3: derive_confidence_tier moved to the model; service re-exports it."""
    journal = _read("apps/backend/src/models/journal.py")
    assert "def derive_confidence_tier(" in journal
    shim = _read("apps/backend/src/services/confidence_tier.py")
    assert (
        "from src.models.journal import ConfidenceTier, derive_confidence_tier" in shim
    )


@ac_proof(
    proof_id="test_ledger_investment_postings_adoption",
    ac_ids=["AC12.34.4"],
    ci_tier="pr_ci",
)
def test_AC12_34_4_investment_postings_use_ledger_post():
    """AC12.34.4: investment buy/sell/dividend post via Entry + post_entry."""
    src = _read("apps/backend/src/services/investment_accounting.py")
    assert "from src.ledger import Entry, Leg, post_entry" in src
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
    ac_ids=["AC12.34.5"],
    ci_tier="pr_ci",
)
def test_AC12_34_5_remaining_posting_paths_guard_balance_with_entry():
    """AC12.34.5: opening-balance and fx-revaluation also gate balance through Entry.

    These were the last two posting paths not covered by Entry — opening-balance
    relied on the create-time check, and fx-revaluation wrote raw JournalLines with
    no balance validation at all. Both now construct an Entry before persisting, so
    every posting path in the codebase is balance-guaranteed as a type.
    """
    for path in (
        "apps/backend/src/services/accounting.py",
        "apps/backend/src/services/fx_revaluation.py",
    ):
        src = _read(path)
        assert "from src.ledger import Entry, Leg" in src, (
            f"{path} must use ledger Entry/Leg"
        )
        assert "Entry.of(" in src, f"{path} must construct an Entry to guard balance"


@ac_proof(
    proof_id="test_ledger_owns_posting_pipeline",
    ac_ids=["AC12.34.6"],
    ci_tier="pr_ci",
)
def test_AC12_34_6_ledger_owns_posting_pipeline_no_upward_edge():
    """AC12.34.6: the journal write pipeline lives in ledger.store; ledger.ops depends
    down on it (not up on services.accounting), dissolving the ledger↔accounting cycle.

    services.accounting re-exports the pipeline so external callers are unchanged.
    """
    assert (SRC / "ledger/store/posting.py").exists()
    post = _read("apps/backend/src/ledger/ops/post.py")
    assert (
        "from src.ledger.store.posting import create_journal_entry, post_journal_entry"
        in post
    )
    assert "from src.services.accounting import" not in post, (
        "ledger.ops must not import upward into services.accounting"
    )
    acct = _read("apps/backend/src/services/accounting.py")
    assert "from src.ledger.store.posting import" in acct, (
        "services.accounting must re-export the pipeline from ledger.store"
    )
    # the pipeline defs no longer live in services.accounting
    assert "async def create_journal_entry(" not in acct
    assert "async def post_journal_entry(" not in acct
