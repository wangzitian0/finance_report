"""AC-testing.benchmarks.4: Bench V2 reads flow domains from the 30-flow registry (moved from the scenario suite, #2318)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_mapping_ssot_bijection_and_coverage() -> None:
    """AC-testing.benchmarks.4: FLOW_TO_CASES covers exactly the flows of the 30-flow registry."""
    from common.testing.benchmarks.case_types import (
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
    """AC-testing.benchmarks.4: FLOW_TO_DOMAIN and FLOW_TO_CASES call registry loaders and hold no literal map."""
    import ast

    from common.testing.benchmarks import case_types

    tree = ast.parse(Path(case_types.__file__).read_text(encoding="utf-8"))
    ann_assigns = {
        node.target.id: node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id in ("FLOW_TO_DOMAIN", "FLOW_TO_CASES")
    }
    assert "FLOW_TO_DOMAIN" in ann_assigns
    assert "FLOW_TO_CASES" in ann_assigns

    for name, value in ann_assigns.items():
        assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name), (
            f"{name} must be a function call"
        )
        assert not any(isinstance(node, ast.Dict) for node in ast.walk(value)), (
            f"{name} must not wrap a literal map"
        )
    assert ann_assigns["FLOW_TO_DOMAIN"].func.id == "load_flow_to_domain"
    assert ann_assigns["FLOW_TO_CASES"].func.id == "load_flow_to_cases"


def test_load_flow_to_domain_follows_registry_edits(tmp_path: Path) -> None:
    """AC-testing.benchmarks.4: the loader maps by the `id` fields, not by list position."""
    from common.testing.benchmarks.case_types import load_flow_to_domain

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
    from common.testing.benchmarks.case_types import load_flow_to_domain

    path = tmp_path / "flows.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="30-flow registry .*flows.json"):
        load_flow_to_domain(path)


def test_load_flow_to_cases_follows_registry_edits(tmp_path: Path) -> None:
    """AC-testing.benchmarks.4: load_flow_to_cases maps by flow id and reads benchmark_cases."""
    from common.testing.benchmarks.case_types import load_flow_to_cases

    registry = {
        "domains": [
            {"id": 2, "flows": [{"id": 3, "benchmark_cases": ["2"]}]},
            {
                "id": 1,
                "flows": [
                    {"id": 1, "benchmark_cases": ["1"]},
                    {"id": 2, "benchmark_cases": ["1", "6"]},
                ],
            },
        ]
    }
    path = tmp_path / "flows.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    assert load_flow_to_cases(path) == {3: ["2"], 1: ["1"], 2: ["1", "6"]}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"groups": []}),
        json.dumps({"domains": [{"id": 1, "flows": [{}]}]}),
        json.dumps({"domains": [{"id": 1, "flows": [{"id": 1}]}]}),
        json.dumps(
            {"domains": [{"id": 1, "flows": [{"id": 1, "benchmark_cases": []}]}]}
        ),
        json.dumps(
            {"domains": [{"id": 1, "flows": [{"id": 1, "benchmark_cases": [1]}]}]}
        ),
    ],
    ids=[
        "malformed-json",
        "no-domains-key",
        "flow-without-id",
        "missing-benchmark-cases",
        "empty-benchmark-cases",
        "non-string-benchmark-cases",
    ],
)
def test_load_flow_to_cases_error_names_the_registry(
    tmp_path: Path, content: str
) -> None:
    """AC-testing.benchmarks.4: a bad registry raises ValueError with the file path."""
    from common.testing.benchmarks.case_types import load_flow_to_cases

    path = tmp_path / "flows.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="30-flow registry .*flows.json"):
        load_flow_to_cases(path)


def test_load_flow_to_cases_missing_file_raises_value_error(tmp_path: Path) -> None:
    """AC-testing.benchmarks.4: missing file raises ValueError naming registry."""
    from common.testing.benchmarks.case_types import load_flow_to_cases

    path = tmp_path / "nonexistent.json"
    with pytest.raises(ValueError, match="30-flow registry .*nonexistent.json"):
        load_flow_to_cases(path)
