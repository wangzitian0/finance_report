"""AC-testing.e2e-description-fidelity.1: the Ping An journey counts misread descriptions (#2932).

The vision model reads the description of 2 interest rows of the Ping An fixture wrongly.
The journey matches each extracted row to the fixture event with the same balance after.
It counts the differences, prints the count, and fails above the known count.
No test here opens a network connection or starts a browser.
The journey module imports playwright and the e2e conftest, so a test reads its source with ast.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNEYS = REPO_ROOT / "tests" / "e2e" / "test_institution_statement_journeys.py"
PINGAN_FIXTURE = (
    REPO_ROOT
    / "common"
    / "testing"
    / "fixtures"
    / "pdf"
    / "generated"
    / "pingan_statement_fixture_expected.json"
)
PINGAN_JOURNEY = "test_pingan_statement_journey"
RUNNER = "_run_institution_journey"
FIDELITY_KEYWORDS = {"expected_events", "known_description_misreads"}
KNOWN_CONSTANT = "PINGAN_KNOWN_DESCRIPTION_MISREADS"
INTEREST = "账户结息"
MISREAD = "账户信息"


def _df() -> ModuleType:
    # Import inside the test body: a missing module fails the test, not the collection.
    return importlib.import_module("tests.e2e.description_fidelity")


def _event(description: str, balance: str) -> dict[str, Any]:
    return {
        "description": description,
        "amount": "1.00",
        "direction": "IN",
        "balance_after": balance,
    }


def _row(description: str | None, balance: Any) -> dict[str, Any]:
    # The rows that the journey reads have `date` None, so a match never uses the date.
    return {"date": None, "description": description, "balance_after": balance}


# ── the counter ─────────────────────────────────────────────────────────────────────────────────


def test_AC_testing_e2e_description_fidelity_1_equal_descriptions_are_not_misreads():
    events = [_event("Salary", "100.00"), _event("Rent", "60.00")]
    rows = [_row("Salary", "100.00"), _row("Rent", "60.00")]

    assert _df().description_misreads(rows, events) == []


def test_AC_testing_e2e_description_fidelity_1_a_whitespace_difference_is_not_a_misread():
    events = [_event("Interest  Earned", "100.00")]
    rows = [_row(" Interest Earned\n", "100.00")]

    assert _df().description_misreads(rows, events) == []


def test_AC_testing_e2e_description_fidelity_1_one_wrong_description_is_one_misread():
    df = _df()
    events = [_event("Salary", "100.00"), _event(INTEREST, "29826.00")]
    rows = [_row("Salary", "100.00"), _row(MISREAD, "29826.00")]

    misreads = df.description_misreads(rows, events)

    assert misreads == [
        df.Misread(
            got=MISREAD,
            want=INTEREST,
            balance_after="29826.00",
            reason="differs",
        )
    ]


def test_AC_testing_e2e_description_fidelity_1_a_row_matches_its_event_by_balance_not_by_position():
    """Rows in reverse order still match. A swapped description is blamed on the row that carries it."""
    events = [
        _event("Salary", "100.00"),
        _event("Rent", "60.00"),
        _event(INTEREST, "61.00"),
    ]
    rows = [_row(MISREAD, "61.00"), _row("Rent", "60.00"), _row("Salary", "100.00")]

    misreads = _df().description_misreads(rows, events)

    assert [(m.got, m.want, m.balance_after) for m in misreads] == [
        (MISREAD, INTEREST, "61.00")
    ]


@pytest.mark.parametrize(
    "balance", ["29826", "29826.00", " 29826.0 ", 29826, Decimal("29826.00")]
)
def test_AC_testing_e2e_description_fidelity_1_a_balance_matches_as_a_decimal_not_as_text(
    balance,
):
    events = [_event(INTEREST, "29826.00")]

    assert _df().description_misreads([_row(INTEREST, balance)], events) == []
    assert [
        m.want for m in _df().description_misreads([_row(MISREAD, balance)], events)
    ] == [INTEREST]


def test_AC_testing_e2e_description_fidelity_1_a_row_that_matches_no_event_is_a_misread():
    df = _df()
    events = [_event("Salary", "100.00")]
    rows = [_row("Salary", "100.00"), _row("Coffee", "99.00")]

    misreads = df.description_misreads(rows, events)

    assert misreads == [
        df.Misread(got="Coffee", want=None, balance_after="99.00", reason="no_event")
    ]


@pytest.mark.parametrize("balance", [None, "", "  ", "abc", "NaN", "Infinity"])
def test_AC_testing_e2e_description_fidelity_1_a_row_without_a_usable_balance_is_a_misread(
    balance,
):
    events = [_event("Salary", "100.00")]
    rows = [_row("Salary", balance)]

    misreads = _df().description_misreads(rows, events)

    assert [(m.got, m.want, m.reason) for m in misreads] == [
        ("Salary", None, "no_balance")
    ]


def test_AC_testing_e2e_description_fidelity_1_a_row_with_no_balance_key_is_a_misread():
    row = {"date": None, "description": "Salary"}

    misreads = _df().description_misreads([row], [_event("Salary", "100.00")])

    assert [(m.want, m.balance_after, m.reason) for m in misreads] == [
        (None, None, "no_balance")
    ]


def test_AC_testing_e2e_description_fidelity_1_two_rows_for_one_event_are_ambiguous():
    """No guess: both rows are reported, also the row whose description equals the event."""
    events = [_event("Salary", "100.00")]
    rows = [_row("Salary", "100.00"), _row("Salary", "100")]

    misreads = _df().description_misreads(rows, events)

    assert [(m.got, m.want, m.reason) for m in misreads] == [
        ("Salary", None, "ambiguous"),
        ("Salary", None, "ambiguous"),
    ]


def test_AC_testing_e2e_description_fidelity_1_two_events_with_one_balance_are_ambiguous():
    events = [_event("Salary", "100.00"), _event("Bonus", "100.00")]

    misreads = _df().description_misreads([_row("Salary", "100.00")], events)

    assert [(m.got, m.want, m.reason) for m in misreads] == [
        ("Salary", None, "ambiguous")
    ]


def test_AC_testing_e2e_description_fidelity_1_a_missing_description_is_compared_as_empty_text():
    events = [_event("Salary", "100.00")]

    misreads = _df().description_misreads([_row(None, "100.00")], events)

    assert [(m.got, m.want, m.reason) for m in misreads] == [("", "Salary", "differs")]


def test_AC_testing_e2e_description_fidelity_1_no_rows_give_no_misread():
    assert _df().description_misreads([], [_event("Salary", "100.00")]) == []


def test_AC_testing_e2e_description_fidelity_1_a_misread_is_immutable():
    misread = _df().Misread(got="a", want="b", balance_after="1.00", reason="differs")

    with pytest.raises(dataclasses.FrozenInstanceError):
        misread.got = "c"  # type: ignore[misc]


# ── the printed line ────────────────────────────────────────────────────────────────────────────


def _interest_misreads() -> list[Any]:
    df = _df()
    return [
        df.Misread(MISREAD, INTEREST, "29826.00", "differs"),
        df.Misread(MISREAD, INTEREST, "31122.00", "differs"),
    ]


def test_AC_testing_e2e_description_fidelity_1_the_line_states_the_count_the_known_count_and_both_texts():
    line = _df().format_misread_line(_interest_misreads(), 2, 15)

    assert line == (
        "description fidelity: 2 of 15 rows differ from the fixture (known 2): "
        f"'{MISREAD}' for '{INTEREST}' (balance after 29826.00), "
        f"'{MISREAD}' for '{INTEREST}' (balance after 31122.00)"
    )
    assert "\n" not in line


def test_AC_testing_e2e_description_fidelity_1_the_line_is_printed_also_for_zero_differences():
    line = _df().format_misread_line([], 2, 15)

    assert (
        line == "description fidelity: 0 of 15 rows differ from the fixture (known 2)"
    )


def _numbered_misreads(count: int) -> list[Any]:
    df = _df()
    return [
        df.Misread(f"got{i}", f"want{i}", f"{i}.00", "differs") for i in range(count)
    ]


def test_AC_testing_e2e_description_fidelity_1_the_line_lists_at_most_five_differences():
    line = _df().format_misread_line(_numbered_misreads(7), 2, 15)

    assert line.startswith("description fidelity: 7 of 15 rows differ")
    assert "'got4' for 'want4' (balance after 4.00)" in line
    assert "got5" not in line
    assert line.endswith(", ...")


def test_AC_testing_e2e_description_fidelity_1_the_line_has_no_ellipsis_for_five_differences():
    line = _df().format_misread_line(_numbered_misreads(5), 2, 15)

    assert "got4" in line
    assert "..." not in line


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("no_event", "no fixture event"),
        ("no_balance", "no usable balance after"),
        ("ambiguous", "ambiguous"),
    ],
)
def test_AC_testing_e2e_description_fidelity_1_the_line_names_the_reason_of_an_unmatched_row(
    reason, text
):
    misread = _df().Misread("Coffee", None, "99.00", reason)

    line = _df().format_misread_line([misread], 0, 15)

    assert "1 of 15 rows differ from the fixture (known 0)" in line
    assert "'Coffee'" in line
    assert text in line


# ── the journey wiring: ast of the journey source ───────────────────────────────────────────────


def _journey_tree() -> ast.Module:
    return ast.parse(JOURNEYS.read_text(encoding="utf-8"))


def _functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }


def _table_calls(tree: ast.Module, table: str) -> dict[str, ast.Call]:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == table
            and isinstance(node.value, ast.Dict)
        ):
            return {
                key.value: value
                for key, value in zip(node.value.keys, node.value.values)
                if isinstance(key, ast.Constant) and isinstance(value, ast.Call)
            }
    raise AssertionError(f"{table} is not a dict literal of calls")


def _disposition_shape(call: ast.Call) -> tuple[Any, Any, Any]:
    """Return (intent, account type, category) of one FixtureDisposition call node."""
    assert isinstance(call.func, ast.Name) and call.func.id == "FixtureDisposition"
    names = ["intent", "account_type", "rationale", "category"]
    values: dict[str, Any] = {}
    for name, arg in zip(names, call.args):
        values[name] = arg
    for keyword in call.keywords:
        assert keyword.arg is not None
        values[keyword.arg] = keyword.value
    return tuple(
        values[name].value if name in values else None
        for name in ("intent", "account_type", "category")
    )  # type: ignore[return-value]


def _module_int(tree: ast.Module, name: str) -> int:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            assert isinstance(node.value, ast.Constant)
            assert isinstance(node.value.value, int)
            return node.value.value
    raise AssertionError(f"{name} is not a module constant")


def _bound_assert(runner: ast.AsyncFunctionDef | ast.FunctionDef) -> ast.Assert:
    asserts = [
        node
        for node in ast.walk(runner)
        if isinstance(node, ast.Assert)
        and isinstance(node.test, ast.Compare)
        and any(
            isinstance(name, ast.Name) and name.id == "misreads"
            for name in ast.walk(node.test)
        )
    ]
    assert len(asserts) == 1, "the journey runner must hold one assert on the misreads"
    return asserts[0]


def test_AC_testing_e2e_description_fidelity_1_the_known_misread_has_the_disposition_of_the_fixture_description():
    """The alias records a known misread. It is not a second vocabulary: its disposition equals the original."""
    calls = _table_calls(_journey_tree(), "PINGAN_DISPOSITIONS")

    assert INTEREST in calls
    assert MISREAD in calls
    assert _disposition_shape(calls[MISREAD]) == _disposition_shape(calls[INTEREST])
    assert _disposition_shape(calls[MISREAD]) == ("income", "INCOME", "INTEREST")


def test_AC_testing_e2e_description_fidelity_1_the_known_count_is_a_constant_of_two():
    assert _module_int(_journey_tree(), KNOWN_CONSTANT) == 2


def test_AC_testing_e2e_description_fidelity_1_only_the_ping_an_journey_passes_the_fidelity_keywords():
    tree = _journey_tree()
    callers: dict[str, set[str]] = {}
    for name, function in _functions(tree).items():
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg in FIDELITY_KEYWORDS:
                        callers.setdefault(name, set()).add(keyword.arg)

    assert callers == {PINGAN_JOURNEY: FIDELITY_KEYWORDS}

    call = next(
        node
        for node in ast.walk(_functions(tree)[PINGAN_JOURNEY])
        if isinstance(node, ast.Call)
        and any(keyword.arg in FIDELITY_KEYWORDS for keyword in node.keywords)
    )
    assert isinstance(call.func, ast.Name) and call.func.id == RUNNER
    values = {keyword.arg: keyword.value for keyword in call.keywords}
    assert ast.unparse(values["expected_events"]) in {
        "expected['events']",
        'expected["events"]',
    }
    known = values["known_description_misreads"]
    assert isinstance(known, ast.Name) and known.id == KNOWN_CONSTANT


def test_AC_testing_e2e_description_fidelity_1_the_runner_defaults_keep_the_other_journeys_unchanged():
    runner = _functions(_journey_tree())[RUNNER]
    defaults = {
        arg.arg: ast.unparse(default)
        for arg, default in zip(runner.args.kwonlyargs, runner.args.kw_defaults)
        if default is not None
    }

    assert defaults["expected_events"] == "None"
    assert defaults["known_description_misreads"] == "0"


def test_AC_testing_e2e_description_fidelity_1_the_runner_reports_and_bounds_before_the_approval():
    runner = _functions(_journey_tree())[RUNNER]
    bound = _bound_assert(runner)
    assert isinstance(bound.test, ast.Compare)
    assert [type(op) for op in bound.test.ops] == [ast.LtE]
    comparator = bound.test.comparators[0]
    assert isinstance(comparator, ast.Name)
    assert comparator.id == "known_description_misreads"

    def first_line(function_name: str) -> int:
        return min(
            node.lineno
            for node in ast.walk(runner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function_name
        )

    approval = first_line("approve_statement_with_fixture_review")
    assert first_line("description_misreads") < approval
    assert first_line("format_misread_line") < approval
    assert bound.lineno < approval

    recorded = [
        node
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "record_property"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "description_misreads"
    ]
    assert recorded, "the runner must record the count as description_misreads"
    assert bound.msg is not None, "the assert must explain the failure"
    message_names = {n.id for n in ast.walk(bound.msg) if isinstance(n, ast.Name)}
    assert {"misreads", "known_description_misreads"} <= message_names


def test_AC_testing_e2e_description_fidelity_1_the_line_is_printed_also_when_no_row_differs():
    """The print call may sit only under the guard on expected_events, never under a guard on the count."""
    runner = _functions(_journey_tree())[RUNNER]
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(runner):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    prints = [
        node
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and any("format_misread_line" in ast.unparse(arg) for arg in node.args)
    ]
    assert len(prints) == 1

    guards = []
    node: ast.AST = prints[0]
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.If):
            guards.append(ast.unparse(node.test))

    assert all("expected_events" in guard for guard in guards), guards
    assert guards, "the print must sit under the guard on expected_events"


# ── the journey rule replayed on the real fixture ───────────────────────────────────────────────


def _journey_bound_holds(count: int, known: int) -> bool:
    """Evaluate the assert of the journey runner for `count` misreads and the `known` count."""
    bound = _bound_assert(_functions(_journey_tree())[RUNNER])
    code = compile(ast.Expression(bound.test), "<journey-assert>", "eval")
    return bool(
        eval(  # noqa: S307 - the expression is the assert of a file in this repository
            code,
            {"__builtins__": {}, "len": len},
            {"misreads": [object()] * count, "known_description_misreads": known},
        )
    )


def _fixture_rows(
    swapped: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = json.loads(PINGAN_FIXTURE.read_text(encoding="utf-8"))["events"]
    rows = []
    for index, event in enumerate(events):
        description = event["description"]
        if description == INTEREST:
            description = MISREAD
        if index in swapped:
            description = description + "x"
        rows.append(_row(description, event["balance_after"]))
    # Reverse order: a counter that matches by position instead of balance after fails here.
    rows.reverse()
    return events, rows


def test_AC_testing_e2e_description_fidelity_1_the_fixture_replay_has_two_interest_rows_to_swap():
    events = json.loads(PINGAN_FIXTURE.read_text(encoding="utf-8"))["events"]

    assert len(events) == 15
    assert [e["description"] for e in events].count(INTEREST) == 2
    assert len({e["balance_after"] for e in events}) == 15


def test_AC_testing_e2e_description_fidelity_1_the_journey_rule_counts_two_swapped_interest_rows_and_rejects_a_third():
    df = _df()
    tree = _journey_tree()
    known = _module_int(tree, KNOWN_CONSTANT)
    events, rows = _fixture_rows(swapped=set())

    # The model output of #2932: the 2 interest rows read as 账户信息, 13 rows equal.
    misreads = df.description_misreads(rows, events)

    assert known == 2
    assert [(m.got, m.want) for m in misreads] == [(MISREAD, INTEREST)] * 2
    assert sorted(m.balance_after for m in misreads) == ["29826.00", "31122.00"]
    assert _journey_bound_holds(len(misreads), known)
    assert df.format_misread_line(misreads, known, len(rows)).startswith(
        "description fidelity: 2 of 15 rows differ from the fixture (known 2): "
    )

    # A third row with a new misread breaks the bound.
    index = next(i for i, e in enumerate(events) if e["description"] == "基金申购")
    events, rows = _fixture_rows(swapped={index})
    misreads = df.description_misreads(rows, events)

    assert len(misreads) == 3
    assert not _journey_bound_holds(len(misreads), known)


def test_AC_testing_e2e_description_fidelity_1_the_fixture_replay_without_a_misread_prints_zero():
    df = _df()
    events = json.loads(PINGAN_FIXTURE.read_text(encoding="utf-8"))["events"]
    rows = [_row(e["description"], e["balance_after"]) for e in events]

    misreads = df.description_misreads(rows, events)

    assert misreads == []
    assert df.format_misread_line(misreads, 2, len(rows)) == (
        "description fidelity: 0 of 15 rows differ from the fixture (known 2)"
    )
