"""AC-testing.benchmarks.4: Bench V2 reads flow domains from the 30-flow registry (moved from the scenario suite, #2318)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_mapping_ssot_bijection_and_coverage() -> None:
    """AC-testing.benchmarks.4: FLOW_TO_CASES covers exactly the flows of the 30-flow registry."""
    from tools._lib.benchmarks.case_types import (
        DOMAIN_TO_CASES,
        FLOW_TO_CASES,
        FLOW_TO_DOMAIN,
        get_case_to_flows,
    )

    # 1. The registry JSON is read here without the case_types loader
    registry = json.loads(
        (REPO_ROOT / "common/meta/flows/thirty_flows_ssot.json").read_text(
            encoding="utf-8"
        )
    )
    registry_domain_of = {
        flow["id"]: domain["id"]
        for domain in registry["domains"]
        for flow in domain["flows"]
    }
    assert len(registry_domain_of) == 30
    assert set(registry_domain_of.values()) == set(range(1, 8))
    assert FLOW_TO_DOMAIN == registry_domain_of
    assert set(FLOW_TO_CASES) == set(registry_domain_of), (
        "FLOW_TO_CASES keys must equal the registry flow ids"
    )

    # 2. Inversion
    computed_case_to_flows = get_case_to_flows()

    # 3. Mathematical bidirectional bijection
    for flow, cases in FLOW_TO_CASES.items():
        assert len(cases) > 0, (
            f"Flow {flow} must be mapped to at least one benchmark case"
        )
        for case in cases:
            cid = f"case_{case}"
            assert cid in computed_case_to_flows, (
                f"Case {cid} missing from inverted map"
            )
            assert flow in computed_case_to_flows[cid], (
                f"Flow {flow} missing from {cid}"
            )

    for cid, flows in computed_case_to_flows.items():
        case_num = cid.replace("case_", "")
        for flow in flows:
            assert case_num in FLOW_TO_CASES[flow], (
                f"Case {case_num} missing from FLOW_TO_CASES[{flow}]"
            )

    # 4. Domain to cases alignment
    assert len(DOMAIN_TO_CASES) == 7
    for domain_id, cases in DOMAIN_TO_CASES.items():
        assert len(cases) > 0, f"Domain {domain_id} must cover at least one case"


def test_flow_to_domain_is_derived_not_declared() -> None:
    """AC-testing.benchmarks.4: FLOW_TO_DOMAIN is a call to the registry loader and holds no literal map."""
    import ast

    from tools._lib.benchmarks import case_types

    tree = ast.parse(Path(case_types.__file__).read_text(encoding="utf-8"))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "FLOW_TO_DOMAIN"
    ]
    assert len(values) == 1
    value = values[0]
    assert (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "load_flow_to_domain"
    ), "FLOW_TO_DOMAIN must be load_flow_to_domain(...)"
    assert not any(isinstance(node, ast.Dict) for node in ast.walk(value)), (
        "FLOW_TO_DOMAIN must not wrap a literal map"
    )


def test_load_flow_to_domain_follows_registry_edits(tmp_path: Path) -> None:
    """AC-testing.benchmarks.4: the loader maps by the `id` fields, not by list position."""
    from tools._lib.benchmarks.case_types import load_flow_to_domain

    # Domain 2 is listed before domain 1, so a position-based map gives a wrong answer.
    registry = {
        "domains": [
            {"id": 2, "flows": [{"id": 3}]},
            {"id": 1, "flows": [{"id": 1}, {"id": 2}]},
        ]
    }
    path = tmp_path / "flows.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert load_flow_to_domain(path) == {3: 2, 1: 1, 2: 1}

    registry["domains"][0]["flows"].append({"id": 4})
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert load_flow_to_domain(path) == {3: 2, 4: 2, 1: 1, 2: 1}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"groups": []}),
        json.dumps({"domains": [{"id": 1, "flows": [{}]}]}),
    ],
    ids=["malformed-json", "no-domains-key", "flow-without-id"],
)
def test_load_flow_to_domain_error_names_the_registry(
    tmp_path: Path, content: str
) -> None:
    """AC-testing.benchmarks.4: a bad registry raises ValueError with the file path."""
    from tools._lib.benchmarks.case_types import load_flow_to_domain

    path = tmp_path / "flows.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="30-flow registry .*flows.json"):
        load_flow_to_domain(path)
