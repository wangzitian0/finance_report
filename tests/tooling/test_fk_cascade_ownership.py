"""AC-audit.deletion-ownership.1: exact ownership for DB cascades (#1848)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path

import pytest

from common.audit.extension.cascade_ownership import (
    DEBT_BASELINE_PATH,
    INVENTORY_PATH,
    CascadeInventoryError,
    discover_cascades,
    load_debt_baseline,
    load_inventory,
    validate_debt_ratchet,
    validate_inventory,
)

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"


def test_AC_audit_deletion_ownership_1_inventory_is_exact_and_valid() -> None:
    sites = discover_cascades(SRC)
    inventory = load_inventory(INVENTORY_PATH)
    debt_baseline = load_debt_baseline(DEBT_BASELINE_PATH)

    validate_inventory(sites, inventory)
    validate_debt_ratchet(inventory, debt_baseline)

    assert len(sites) == 48
    classes = Counter(record.classification for record in inventory)
    assert classes["aggregate_internal"] == 11
    assert classes["purge_owned"] == 27
    assert classes["cross_domain"] == 7
    assert classes["retention_sensitive"] == 3

    retention_sites = {
        record.site
        for record in inventory
        if record.classification == "retention_sensitive"
    }
    assert retention_sites == {
        "extraction/orm/correction.py::CorrectionLog.transaction_id"
        "->atomic_transactions.id",
        "extraction/orm/layer3.py::TransactionClassification.rule_version_id"
        "->classification_rules.id",
        "portfolio/orm/portfolio.py::InvestmentLot.opening_transaction_id"
        "->investment_transactions.id",
    }


def test_AC_audit_deletion_ownership_1_discovery_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(CascadeInventoryError, match="no CASCADE declarations"):
        discover_cascades(tmp_path)


def test_AC_audit_deletion_ownership_1_rejects_unclassified_site() -> None:
    sites = discover_cascades(SRC)
    inventory = load_inventory(INVENTORY_PATH)

    with pytest.raises(CascadeInventoryError, match="inventory does not equal"):
        validate_inventory(sites, inventory[:-1])


def test_AC_audit_deletion_ownership_1_rejects_false_internal_owner() -> None:
    sites = discover_cascades(SRC)
    inventory = list(load_inventory(INVENTORY_PATH))
    debt_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification == "cross_domain"
    )
    debt = inventory[debt_index]
    inventory[debt_index] = replace(debt, classification="aggregate_internal")

    with pytest.raises(CascadeInventoryError, match="aggregate_internal"):
        validate_inventory(sites, inventory)


def test_AC_audit_deletion_ownership_1_rejects_forged_target_owner() -> None:
    sites = discover_cascades(SRC)
    inventory = list(load_inventory(INVENTORY_PATH))
    debt_index = next(
        index
        for index, record in enumerate(inventory)
        if "ManagedPosition.account_id->accounts.id" in record.site
    )
    debt = inventory[debt_index]
    inventory[debt_index] = replace(
        debt,
        target_owner=debt.source_owner,
        classification="aggregate_internal",
        issue=None,
    )

    with pytest.raises(CascadeInventoryError, match="target_owner must be 'ledger'"):
        validate_inventory(sites, inventory)


def test_AC_audit_deletion_ownership_1_discovers_module_level_table(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sample"
    package.mkdir()
    (package / "models.py").write_text(
        "class Parent:\n"
        "    __tablename__ = 'parents'\n"
        "association = Table(\n"
        "    'association', metadata,\n"
        "    Column('parent_id', ForeignKey('parents.id', ondelete='CASCADE')),\n"
        ")\n",
        encoding="utf-8",
    )

    sites = discover_cascades(tmp_path)

    assert len(sites) == 1
    assert sites[0].site == "sample/models.py::association.parent_id->parents.id"
    assert sites[0].source_owner == "sample"
    assert sites[0].target_owner == "sample"


def test_AC_audit_deletion_ownership_1_discovers_composite_foreign_keys(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sample"
    package.mkdir()
    (package / "models.py").write_text(
        "class Parent:\n"
        "    __tablename__ = 'parents'\n"
        "class Link:\n"
        "    __tablename__ = 'links'\n"
        "    __table_args__ = (\n"
        "        ForeignKeyConstraint(\n"
        "            ['tenant_id', 'parent_id'],\n"
        "            ['parents.tenant_id', 'parents.id'],\n"
        "            name='fk_links_parent',\n"
        "            ondelete='CASCADE',\n"
        "        ),\n"
        "    )\n",
        encoding="utf-8",
    )

    sites = discover_cascades(tmp_path)

    assert len(sites) == 1
    assert sites[0].site == (
        "sample/models.py::Link.__table_args__.fk_links_parent"
        "->parents.tenant_id+parents.id"
    )
    assert sites[0].target_table == "parents"
    assert sites[0].target_owner == "sample"


def test_AC_audit_deletion_ownership_1_expands_mixin_cascades_to_mapped_consumers(
    tmp_path: Path,
) -> None:
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "models.py").write_text(
        "class User:\n    __tablename__ = 'users'\n",
        encoding="utf-8",
    )
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / "mixins.py").write_text(
        "class TenantMixin:\n"
        "    user_id = mapped_column(\n"
        "        ForeignKey('users.id', ondelete='CASCADE')\n"
        "    )\n",
        encoding="utf-8",
    )
    for owner, class_name, table_name in (
        ("alpha", "AlphaRecord", "alpha_records"),
        ("beta", "BetaRecord", "beta_records"),
    ):
        package = tmp_path / owner
        package.mkdir()
        base_declaration = (
            "class DomainBase(TenantMixin):\n    pass\n" if owner == "alpha" else ""
        )
        import_declaration = (
            "from platform.mixins import TenantMixin as OwnedMixin\n"
            if owner == "beta"
            else ""
        )
        base_name = "DomainBase" if owner == "alpha" else "OwnedMixin"
        (package / "models.py").write_text(
            f"{import_declaration}{base_declaration}"
            f"class {class_name}({base_name}):\n"
            f"    __tablename__ = '{table_name}'\n",
            encoding="utf-8",
        )
    override = tmp_path / "override"
    override.mkdir()
    (override / "models.py").write_text(
        "class OverrideRecord(TenantMixin):\n"
        "    __tablename__ = 'override_records'\n"
        "    user_id = mapped_column(ForeignKey('users.id'))\n",
        encoding="utf-8",
    )
    intermediate_override = tmp_path / "intermediate_override"
    intermediate_override.mkdir()
    (intermediate_override / "models.py").write_text(
        "class NoCascadeMixin(TenantMixin):\n"
        "    user_id = mapped_column(ForeignKey('users.id'))\n"
        "class IntermediateOverrideRecord(NoCascadeMixin):\n"
        "    __tablename__ = 'intermediate_override_records'\n",
        encoding="utf-8",
    )

    sites = discover_cascades(tmp_path)

    assert [site.site for site in sites] == [
        "alpha/models.py::AlphaRecord.user_id->users.id",
        "beta/models.py::BetaRecord.user_id->users.id",
    ]
    assert [site.source_owner for site in sites] == ["alpha", "beta"]
    assert {site.target_owner for site in sites} == {"identity"}


@pytest.mark.parametrize(
    ("imports", "foreign_key", "expected_site"),
    [
        (
            "from sqlalchemy import ForeignKey as FK\n",
            "FK('users.id', ondelete='cascade')",
            "sample/models.py::Sample.user_id->users.id",
        ),
        (
            "",
            "ForeignKey('users.id', None, False, None, None, 'CASCADE')",
            "sample/models.py::Sample.user_id->users.id",
        ),
        (
            "",
            "ForeignKeyConstraint(['user_id'], ['users.id'], "
            "'fk_sample_user', None, 'cascade')",
            "sample/models.py::Sample.__table_args__.fk_sample_user->users.id",
        ),
    ],
    ids=["aliased-lowercase", "scalar-positional", "composite-positional"],
)
def test_AC_audit_deletion_ownership_1_normalizes_equivalent_cascade_syntax(
    tmp_path: Path, imports: str, foreign_key: str, expected_site: str
) -> None:
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "models.py").write_text(
        "class User:\n    __tablename__ = 'users'\n",
        encoding="utf-8",
    )
    sample = tmp_path / "sample"
    sample.mkdir()
    if "Constraint" in foreign_key:
        declaration = f"    __table_args__ = ({foreign_key},)\n"
    else:
        declaration = f"    user_id = mapped_column({foreign_key})\n"
    (sample / "models.py").write_text(
        f"{imports}class Sample:\n    __tablename__ = 'samples'\n{declaration}",
        encoding="utf-8",
    )

    sites = discover_cascades(tmp_path)

    assert [site.site for site in sites] == [expected_site]
    assert sites[0].source_owner == "sample"
    assert sites[0].target_owner == "identity"


def test_AC_audit_deletion_ownership_1_rejects_unresolved_mixin_cascade(
    tmp_path: Path,
) -> None:
    package = tmp_path / "platform"
    package.mkdir()
    (package / "mixins.py").write_text(
        "class TenantMixin:\n"
        "    user_id = mapped_column(\n"
        "        ForeignKey('users.id', ondelete='CASCADE')\n"
        "    )\n",
        encoding="utf-8",
    )

    with pytest.raises(CascadeInventoryError, match="has no mapped consumers"):
        discover_cascades(tmp_path)


@pytest.mark.parametrize("ambiguous", [False, True], ids=["missing", "ambiguous"])
def test_AC_audit_deletion_ownership_1_rejects_unresolved_target_owner(
    tmp_path: Path, ambiguous: bool
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "models.py").write_text(
        "class Child:\n"
        "    __tablename__ = 'children'\n"
        "    parent_id = mapped_column(\n"
        "        ForeignKey('parents.id', ondelete='CASCADE')\n"
        "    )\n",
        encoding="utf-8",
    )
    if ambiguous:
        for owner in ("alpha", "beta"):
            package = tmp_path / owner
            package.mkdir()
            (package / "models.py").write_text(
                "class Parent:\n    __tablename__ = 'parents'\n",
                encoding="utf-8",
            )

    message = "ambiguous owner" if ambiguous else "has no literal table owner"
    with pytest.raises(CascadeInventoryError, match=message):
        discover_cascades(tmp_path)


def test_AC_audit_deletion_ownership_1_retires_coarse_meta_baseline() -> None:
    assert not (REPO / "common/meta/data/fk-cascade-baseline.json").exists()
    assert not (REPO / "tests/tooling/test_fk_cascade_ratchet.py").exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "non-empty list"),
        ([{"site": "incomplete"}], "must have exactly"),
        (
            [
                {
                    "site": "sample.py::Sample.parent_id->parents.id",
                    "source_owner": "sample",
                    "target_owner": "sample",
                    "classification": "unknown",
                    "rationale": "A sufficiently specific rationale.",
                    "issue": None,
                }
            ],
            "unknown classification",
        ),
    ],
)
def test_AC_audit_deletion_ownership_1_rejects_invalid_inventory_payloads(
    tmp_path: Path, payload: object, message: str
) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CascadeInventoryError, match=message):
        load_inventory(path)


def test_AC_audit_deletion_ownership_1_rejects_duplicate_inventory(
    tmp_path: Path,
) -> None:
    record = load_inventory(INVENTORY_PATH)[0]
    payload = [record.__dict__, record.__dict__]
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CascadeInventoryError, match="duplicate sites"):
        load_inventory(path)


def test_AC_audit_deletion_ownership_1_rejects_unreviewable_decisions() -> None:
    sites = discover_cascades(SRC)
    inventory = list(load_inventory(INVENTORY_PATH))
    internal_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification == "aggregate_internal"
    )
    purge_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification == "purge_owned"
    )
    cross_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification == "cross_domain"
    )
    retention_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification == "retention_sensitive"
    )

    mutations = [
        (internal_index, {"source_owner": "wrong"}, "source_owner must be"),
        (internal_index, {"rationale": "short"}, "rationale is not reviewable"),
        (internal_index, {"issue": "#1848"}, "cannot carry debt"),
        (
            purge_index,
            {"target_owner": inventory[purge_index].source_owner},
            "target_owner must be",
        ),
        (purge_index, {"issue": None}, "purge-owned debt"),
        (
            cross_index,
            {"target_owner": inventory[cross_index].source_owner},
            "target_owner must be",
        ),
        (cross_index, {"issue": None}, "cross-domain debt"),
        (
            retention_index,
            {"target_owner": "wrong"},
            "target_owner must be",
        ),
        (retention_index, {"issue": None}, "retention-sensitive debt"),
    ]
    for index, changes, message in mutations:
        candidate = list(inventory)
        candidate[index] = replace(candidate[index], **changes)
        with pytest.raises(CascadeInventoryError, match=message):
            validate_inventory(sites, candidate)


@pytest.mark.parametrize(
    ("foreign_key", "message"),
    [
        ('ForeignKey(ondelete="CASCADE")', "no target argument"),
        ('ForeignKey(target, ondelete="CASCADE")', "target must be a literal"),
        (
            "ForeignKey('parents.id', ondelete=DELETE_POLICY)",
            "ondelete must be a literal",
        ),
        (
            "ForeignKey('parents.id', **{'ondelete': 'CASCADE'})",
            "unpacked arguments",
        ),
    ],
)
def test_AC_audit_deletion_ownership_1_rejects_opaque_targets(
    tmp_path: Path, foreign_key: str, message: str
) -> None:
    package = tmp_path / "sample"
    package.mkdir()
    (package / "models.py").write_text(
        f"class Sample:\n    parent_id = mapped_column({foreign_key})\n",
        encoding="utf-8",
    )

    with pytest.raises(CascadeInventoryError, match=message):
        discover_cascades(tmp_path)


@pytest.mark.parametrize(
    ("constraint", "message"),
    [
        (
            "ForeignKeyConstraint(['parent_id'], ondelete='CASCADE')",
            "has no remote target argument",
        ),
        (
            "ForeignKeyConstraint(['parent_id'], targets, "
            "name='fk_sample_parent', ondelete='CASCADE')",
            "remote targets must be literal",
        ),
        (
            "ForeignKeyConstraint(['parent_id'], ['parents.id'], ondelete='CASCADE')",
            "must have a literal name",
        ),
        (
            "ForeignKeyConstraint(['left_id', 'right_id'], "
            "['parents.id', 'others.id'], name='fk_sample_mixed', "
            "ondelete='CASCADE')",
            "must reference one target table",
        ),
    ],
)
def test_AC_audit_deletion_ownership_1_rejects_opaque_composite_targets(
    tmp_path: Path, constraint: str, message: str
) -> None:
    package = tmp_path / "sample"
    package.mkdir()
    (package / "models.py").write_text(
        f"class Sample:\n    __table_args__ = ({constraint},)\n",
        encoding="utf-8",
    )

    with pytest.raises(CascadeInventoryError, match=message):
        discover_cascades(tmp_path)


def test_AC_audit_deletion_ownership_1_debt_ratchet_rejects_growth() -> None:
    inventory = list(load_inventory(INVENTORY_PATH))
    baseline = load_debt_baseline(DEBT_BASELINE_PATH)
    survivor = next(
        record for record in inventory if record.classification == "aggregate_internal"
    )
    inventory.append(
        replace(
            survivor,
            site="sample/orm.py::Sample.parent_id->parents.id",
            classification="retention_sensitive",
            issue="#1848",
        )
    )

    with pytest.raises(CascadeInventoryError, match="cascade debt grew"):
        validate_debt_ratchet(inventory, baseline)


def test_AC_audit_deletion_ownership_1_debt_ratchet_requires_pruning() -> None:
    inventory = list(load_inventory(INVENTORY_PATH))
    baseline = load_debt_baseline(DEBT_BASELINE_PATH)
    debt_index = next(
        index
        for index, record in enumerate(inventory)
        if record.classification != "aggregate_internal"
    )
    inventory.pop(debt_index)

    with pytest.raises(CascadeInventoryError, match="resolved debt remains baselined"):
        validate_debt_ratchet(inventory, baseline)


@pytest.mark.parametrize(
    "payload",
    [
        {"debt_sites": "not-a-list"},
        {"debt_sites": ["duplicate", "duplicate"]},
        {"debt_sites": [1]},
        {"debt_sites": [], "unexpected": []},
    ],
)
def test_AC_audit_deletion_ownership_1_rejects_invalid_debt_baseline(
    tmp_path: Path, payload: object
) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CascadeInventoryError, match="debt baseline"):
        load_debt_baseline(path)
