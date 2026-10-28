"""Guard that ExchangeRateLookup is the single FX rate port in apps/backend/src (#2774)."""

from __future__ import annotations

import ast
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO / "apps/backend/src"
CANONICAL_OWNER = ("pricing/extension/fx.py", "ExchangeRateLookup")

FX_CALL_FIRST_FOUR_ARGS = ["db", "base_currency", "quote_currency", "rate_date"]


def _is_protocol_base(base: ast.expr) -> bool:
    if isinstance(base, ast.Name):
        return base.id == "Protocol"
    if isinstance(base, ast.Attribute):
        return base.attr == "Protocol"
    return False


def _call_pos_arg_names(cls_node: ast.ClassDef) -> list[str] | None:
    for item in cls_node.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "__call__"
        ):
            args = [arg.arg for arg in item.args.posonlyargs + item.args.args]
            if args and args[0] == "self":
                args = args[1:]
            return args
    return None


def _method_names(cls_node: ast.ClassDef) -> set[str]:
    return {
        item.name
        for item in cls_node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def find_fx_rate_protocols(
    src_root: Path = BACKEND_SRC,
) -> tuple[int, list[tuple[str, str]]]:
    """Scan all Python files under src_root and return (protocol_count, fx_rate_protocols).

    Matches any Protocol class by structural shape regardless of class name:
    1. A callable Protocol whose ``__call__`` takes ``(db, base_currency, quote_currency, rate_date, ...)``
       or ``(db, base_currency, quote_currency, rate_dates, ...)`` (covers spot-rate and series ports).
    2. A Protocol class that declares both ``prefetch`` and ``get_rate`` methods (covers prefetch ports).
    """
    protocol_count = 0
    fx_protocols: list[tuple[str, str]] = []
    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(src_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_is_protocol_base(base) for base in node.bases):
                continue
            protocol_count += 1
            pos_args = _call_pos_arg_names(node)
            if pos_args is not None and (
                pos_args[:4] == FX_CALL_FIRST_FOUR_ARGS
                or pos_args[:4]
                == ["db", "base_currency", "quote_currency", "rate_dates"]
            ):
                fx_protocols.append((rel, node.name))
                continue
            methods = _method_names(node)
            if {"prefetch", "get_rate"} <= methods:
                fx_protocols.append((rel, node.name))
    return protocol_count, fx_protocols


@ac_proof(
    proof_id="single_fx_rate_port",
    ac_ids=["AC-pricing.fx.5"],
    ci_tier="pr_ci",
)
def test_AC_pricing_fx_5_exchange_rate_lookup_is_the_one_fx_rate_port(
    tmp_path: Path,
) -> None:
    """AC-pricing.fx.5: ExchangeRateLookup is the single FX rate port in apps/backend/src."""
    protocol_count, fx_protocols = find_fx_rate_protocols(BACKEND_SRC)
    assert protocol_count >= 15, (
        f"expected non-empty Protocol scan across backend src, got {protocol_count}"
    )
    assert fx_protocols == [CANONICAL_OWNER], (
        f"expected only {CANONICAL_OWNER} as FX rate port, found {fx_protocols}"
    )

    assert not (BACKEND_SRC / "reporting/extension/fx_gateway.py").exists()

    # Probe that a renamed copy or prefetch port is caught by shape.
    probe_pkg = tmp_path / "shadow"
    probe_pkg.mkdir()
    (probe_pkg / "ports.py").write_text(
        "from typing import Protocol\n"
        "class RenamedSpotPort(Protocol):\n"
        "    def __call__(self, db, base_currency, quote_currency, rate_date, *, lazy_load=False): ...\n"
        "class RenamedSeriesPort(Protocol):\n"
        "    def __call__(self, db, base_currency, quote_currency, rate_dates, *, lazy_load=False): ...\n"
        "class RenamedPrefetchPort(Protocol):\n"
        "    async def prefetch(self, db, requests): ...\n"
        "    def get_rate(self, source, target, rate_date): ...\n",
        encoding="utf-8",
    )
    probe_count, probe_hits = find_fx_rate_protocols(tmp_path)
    assert probe_count == 3
    assert probe_hits == [
        ("shadow/ports.py", "RenamedSpotPort"),
        ("shadow/ports.py", "RenamedSeriesPort"),
        ("shadow/ports.py", "RenamedPrefetchPort"),
    ]
