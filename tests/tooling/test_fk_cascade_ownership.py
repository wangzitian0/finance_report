"""AC-audit.deletion-ownership.1: exact ownership for DB cascades (#1848)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path

import pytest

from common.audit.extension.cascade_ownership import (
    INVENTORY_PATH,
    CascadeInventoryError,
    discover_cascades,
    load_inventory,
    validate_inventory,
)

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"


def test_AC_audit_deletion_ownership_1_inventory_is_exact_and_valid() -> None:
    sites = discover_cascades(SRC)
    inventory = load_inventory(INVENTORY_PATH)

    validate_inventory(sites, inventory)

    assert len(sites) == 27
    classes = Counter(record.classification for record in inventory)
    assert classes["aggregate_internal"] > 0
    assert classes["purge_owned"] > 0
    assert classes["cross_domain"] > 0


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

    mutations = [
        (internal_index, {"source_owner": "wrong"}, "source_owner must be"),
        (internal_index, {"rationale": "short"}, "rationale is not reviewable"),
        (internal_index, {"issue": "#1848"}, "cannot carry debt"),
        (
            purge_index,
            {"target_owner": inventory[purge_index].source_owner},
            "purge_owned",
        ),
        (purge_index, {"issue": None}, "purge-owned debt"),
        (
            cross_index,
            {"target_owner": inventory[cross_index].source_owner},
            "cross_domain",
        ),
        (cross_index, {"issue": None}, "cross-domain debt"),
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
